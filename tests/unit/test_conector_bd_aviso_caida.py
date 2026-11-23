"""La línea que vigila la alerta de «base no disponible»: sale cuando la conexión falla en horario y no sale
fuera de horario, cuando la base está apagada a propósito. Tampoco vuelca el texto de la excepción. Una variable de entorno
que falta también avisa: para quien intenta conectarse es la misma caída. Al final, el TLS hacia la base."""

import logging

import pytest
from conector_apoyo import cr

from src.conector import bd


def _falla():
    raise ConnectionRefusedError("10.0.0.1:5432 con datos de la consulta")


@pytest.fixture(autouse=True)
def fabrica_que_falla():
    bd.usar(estado=_falla, lectura=_falla)
    yield
    bd.usar()


def test_en_horario_registra_la_caida_sin_el_texto_de_la_excepcion(monkeypatch, caplog):
    monkeypatch.setattr(bd, "_ahora", lambda: cr("2026-11-19 10:00"))
    with caplog.at_level(logging.INFO, logger="src.conector.bd"), pytest.raises(bd.BDNoDisponible):
        bd.conectar_lectura()
    avisos = [r.getMessage() for r in caplog.records if bd.AVISO_EN_HORARIO in r.getMessage()]
    assert avisos == [f"{bd.AVISO_EN_HORARIO}: ConnectionRefusedError"]
    assert "datos de la consulta" not in caplog.text


def test_fuera_de_horario_no_avisa(monkeypatch, caplog):
    from src.conector import limites
    monkeypatch.setattr(limites, "SERVICIO_24_HORAS", False)  # el horario de 7 a 23 queda como vuelta atrás
    monkeypatch.setattr(bd, "_ahora", lambda: cr("2026-11-19 06:30"))  # control negativo: antes de las 7:00 la base está apagada
    with caplog.at_level(logging.INFO, logger="src.conector.bd"), pytest.raises(bd.BDNoDisponible):
        bd.conectar_lectura()
    assert bd.AVISO_EN_HORARIO not in caplog.text


def test_una_variable_que_falta_tambien_avisa(monkeypatch, caplog):
    def sin_variable():
        raise KeyError("REPLICA_DB_HOST")
    bd.usar(estado=sin_variable, lectura=sin_variable)
    monkeypatch.setattr(bd, "_ahora", lambda: cr("2026-11-19 10:00"))
    with caplog.at_level(logging.INFO, logger="src.conector.bd"), pytest.raises(bd.BDNoDisponible, match="falta configurar"):
        bd.conectar_lectura()
    assert f"{bd.AVISO_EN_HORARIO}: falta configurar REPLICA_DB_HOST" in caplog.text


def test_con_la_ca_de_cloud_sql_la_conexion_va_con_tls_que_verifica_la_cadena(monkeypatch):
    import ssl
    import pg8000.dbapi
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from datetime import datetime, timedelta, timezone
    clave = ec.generate_private_key(ec.SECP256R1())
    nombre = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "CA de prueba")])
    ahora = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre).public_key(clave.public_key())
            .serial_number(1).not_valid_before(ahora).not_valid_after(ahora + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(clave, hashes.SHA256()))
    visto = {}
    monkeypatch.setattr(pg8000.dbapi, "connect", lambda **kw: _Conexion(visto, kw))
    for k, v in {"REPLICA_DB_HOST": "10.0.0.1", "REPLICA_DB_USER": "conector", "REPLICA_DB_PASSWORD": "x"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("REPLICA_DB_CA", cert.public_bytes(serialization.Encoding.PEM).decode())
    bd._postgres()
    ctx = visto["ssl_context"]
    assert isinstance(ctx, ssl.SSLContext) and ctx.verify_mode == ssl.CERT_REQUIRED and not ctx.check_hostname
    assert len(ctx.get_ca_certs()) == 1
    monkeypatch.delenv("REPLICA_DB_CA")  # control negativo: sin la CA, sin TLS (entornos locales y pruebas)
    bd._postgres()
    assert visto["ssl_context"] is None


def _cert(nombre, clave_publica, emisor, clave_firma, ca):
    """Certificado con la forma de los que emite el servicio de base de datos administrada: sin Subject ni Authority
    Key Identifier. Con esa forma, el modo estricto de Python >= 3.13 rechaza la cadena aunque la CA sea la correcta."""
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    ahora = datetime.now(timezone.utc)
    b = (x509.CertificateBuilder().subject_name(nombre).issuer_name(emisor).public_key(clave_publica)
         .serial_number(x509.random_serial_number()).not_valid_before(ahora - timedelta(minutes=5))
         .not_valid_after(ahora + timedelta(days=1)))
    if ca:
        b = b.add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
    return b.sign(clave_firma, hashes.SHA256())


def _apreton(ctx_cliente, cert_servidor, clave_servidor, tmp_path):
    """Apretón de manos TLS real en memoria entre el contexto del conector y un servidor con ese certificado."""
    import ssl
    from cryptography.hazmat.primitives import serialization
    pem = tmp_path / "servidor.pem"
    pem.write_bytes(cert_servidor.public_bytes(serialization.Encoding.PEM) + clave_servidor.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    ctx_servidor = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx_servidor.load_cert_chain(pem)
    a, b, c, d = ssl.MemoryBIO(), ssl.MemoryBIO(), ssl.MemoryBIO(), ssl.MemoryBIO()
    cliente = ctx_cliente.wrap_bio(a, b, server_hostname="10.0.0.1")
    servidor = ctx_servidor.wrap_bio(c, d, server_side=True)
    for _ in range(10):
        hechos = 0
        for lado in (cliente, servidor):
            try:
                lado.do_handshake()
                hechos += 1
            except ssl.SSLWantReadError:
                pass
        c.write(b.read())
        a.write(d.read())
        if hechos == 2:
            return
    raise AssertionError("el apretón de manos no terminó")


def test_el_certificado_con_la_forma_del_de_cloud_sql_pasa_y_uno_de_otra_ca_no(monkeypatch, tmp_path):
    """Con la CA correcta, la conexión TLS daba SSLCertVerificationError: el modo estricto de Python
    3.14 exige identificadores de clave que los certificados del servicio no traen. Una prueba que solo mire el contexto, sin
    apretón de manos y con un certificado «perfecto», no lo ve."""
    import ssl
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    n = lambda cn: x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, cn)])  # noqa: E731
    k_ca, k_srv, k_otra = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
    ca = _cert(n("Cloud SQL Server CA"), k_ca.public_key(), n("Cloud SQL Server CA"), k_ca, ca=True)
    servidor = _cert(n("base-de-datos"), k_srv.public_key(), n("Cloud SQL Server CA"), k_ca, ca=False)
    monkeypatch.setenv("REPLICA_DB_CA", ca.public_bytes(serialization.Encoding.PEM).decode())
    _apreton(bd.contexto_tls(), servidor, k_srv, tmp_path)  # control positivo: la CA de la instancia
    otra_ca = _cert(n("Otra CA"), k_otra.public_key(), n("Otra CA"), k_otra, ca=True)
    intruso = _cert(n("base-de-datos"), k_srv.public_key(), n("Otra CA"), k_otra, ca=False)
    assert otra_ca is not None
    with pytest.raises(ssl.SSLCertVerificationError):  # control negativo: la cadena se sigue verificando
        _apreton(bd.contexto_tls(), intruso, k_srv, tmp_path)


class _Conexion:
    def __init__(self, visto, kw):
        visto.update(kw)
        self._usock = None
