"""El conector le prohíbe al asistente citar normas de memoria y prometer escritos listos.

Caso: ChatGPT, con Aiéntika conectado, armó un amparo contra la CCSS citando los artículos 21, 73 y 48 de la Constitución de
memoria (Aiéntika no los entregó) y prometió un documento «listo para presentar ante la Sala Constitucional». OpenAI
recomienda poner lo crítico en los primeros 512 caracteres de `instructions`.
"""

from src.conector.instrucciones import INSTRUCCIONES

REGLA = "NO cites artículos de la Constitución, leyes ni reglamentos de memoria"


def test_la_regla_de_normas_de_memoria_esta_en_los_primeros_512_caracteres():
    assert REGLA in INSTRUCCIONES[:512]
    assert "hay que verificar su texto vigente" in INSTRUCCIONES[:512]


def test_no_promete_escritos_listos_para_presentar():
    assert "No prometas un escrito «listo para presentar»" in INSTRUCCIONES
    assert "lo revisa y lo firma quien lo presenta" in INSTRUCCIONES


def test_pide_usar_agentika_primero_antes_que_la_web():
    # ChatGPT fue a la web por los artículos.
    from src.conector import servidor
    import inspect
    assert INSTRUCCIONES.startswith("Usá Aiéntika PRIMERO, antes de buscar en la web")  # un solo conector
    assert "Usala PRIMERO, antes de buscar en la web" in inspect.getsource(servidor)
    assert "Hacé UNA sola búsqueda" not in INSTRUCCIONES  # sonaba a «usala poco»


def test_la_palabra_agentika_obliga_a_usar_el_conector():
    # La página le dice al usuario que escriba «agentika»; las instrucciones le dicen al asistente que entonces
    # lo use sí o sí (en los primeros 512 caracteres). Lo ideal es usarlo siempre, y con más razón si se pide expresamente.
    assert INSTRUCCIONES.startswith("Usá Aiéntika PRIMERO")  # siempre
    assert "Si la persona escribe «aientika» o «agentika» o pide usarla, usala sí o sí." in INSTRUCCIONES[:512]  # sobre todo si lo pide


def test_agentika_ayudame_inicia_la_guia_del_caso():
    # La frase «agentika ayudame» abre una guía de cuatro pasos para armar el caso.
    assert "«agentika ayudame»" in INSTRUCCIONES
    for paso in ("(1) preguntá qué necesita", "(2) pedí los datos del caso", "(3) buscá la jurisprudencia", "(4) proponé la estructura"):
        assert paso in INSTRUCCIONES


def test_no_ofrece_vias_procesales_de_memoria():
    # ante una pregunta de cobro, Claude usó Aiéntika para el monitorio y agregó «Otras vías (de mi
    # conocimiento, no verificadas por Aiéntika)», con un «proceso ejecutivo simple». La instrucción anterior lo invitaba: «lo que
    # venga de tu propio conocimiento, marcalo como no verificado». Ahora cada vía se busca en la base o no se describe.
    assert "NO ofrezcas de memoria vías procesales, tipos de proceso, plazos ni requisitos" in INSTRUCCIONES
    assert "Antes de mencionar cada una, buscala en Aiéntika" in INSTRUCCIONES
    assert "de tu propio conocimiento, marcalo" not in INSTRUCCIONES


def test_la_fuente_sigue_al_principio():
    # control: agregar la regla no empujó la declaración de la fuente fuera del arranque
    assert INSTRUCCIONES.index("Fuente: base de Aiéntika") < 900
