from fastapi.testclient import TestClient

from ares.config import Config
from ares.orquestrador import criar_orquestrador
from ares.servidor.app import criar_app


def test_radiacode_serves_approved_dashboard_and_packaged_assets(tmp_path):
    orq = criar_orquestrador(Config(fonte_radiacao='radiacode', dados=str(tmp_path),
                                   radiacode_url='ws://127.0.0.1:0/ws'))
    with TestClient(criar_app(orq, orq.teleop)) as client:
        page = client.get('/')
        assert page.status_code == 200 and 'id="radiation-map"' in page.text
        assert '{{INLINE_' not in page.text and 'Configurar fonte' not in page.text
        for name in ('styles.css', 'renderer.js', 'integration.js'):
            response = client.get('/static/approved/' + name)
            assert response.status_code == 200 and len(response.content) > 1000
        assert client.get('/api/estado').json()['robo']['conectado']
        assert client.post('/api/missao/iniciar', json={}).status_code == 409
