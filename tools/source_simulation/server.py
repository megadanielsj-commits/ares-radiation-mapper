"""Fonte e robô simulados com o painel aprovado e o backend ARES original."""
from pathlib import Path
import os
import json

import uvicorn
from fastapi.responses import FileResponse, HTMLResponse

from ares.config import Config
from ares.orquestrador import criar_orquestrador
from ares.servidor.app import ESTATICO, criar_app


def create_app(data_dir=None):
    # Sensibilidade apenas do modelo sintético; não é calibração do Radiacode.
    config = Config(modo="simulacao", fonte_radiacao="padrao", porta=8001,
                    dados=data_dir or os.environ.get("ARES_DADOS", "/app/dados"),
                    cps_por_usvh=80.0)
    orq = criar_orquestrador(config, semente=42)
    orq.definir_fonte_simulada(4.0, 3.0, 8.0)
    app = criar_app(orq, orq.teleop)
    # Substitui somente a apresentação da raiz. APIs e sincronização originais.
    app.router.routes[:] = [route for route in app.router.routes
                           if getattr(route, "path", None) != "/"]
    html = (ESTATICO / "approved/index.html").read_text()
    html = html.replace("RADIACODE USB · GO2 / WEBRTC", "FONTE E ROBÔ SIMULADOS")
    html = html.replace("Aquisição independente", "Fonte simulada")
    html = html.replace("taxa de dose provisória", "dados inteiramente simulados")
    html = html.replace("Gradiente interpolado em CPS", "Campo estimado e medições em CPS")
    html = html.replace("Mapa construído pelas medições", "Campo estimado pelas medições")
    html = html.replace("CONTAGENS MEDIDAS · ESCALA LOGARÍTMICA", "CAMPO ESTIMADO · ESCALA LOGARÍTMICA")
    fields = '''
        <details style="margin-top:14px"><summary>Configurar fonte simulada</summary>
        <div class="coordinate-grid">
          <label><span>Fonte X</span><div class="input-unit"><input id="sim-x" type="number" step="0.1" value="4"><b>m</b></div></label>
          <label><span>Fonte Y</span><div class="input-unit"><input id="sim-y" type="number" step="0.1" value="3"><b>m</b></div></label>
        </div>
        <label class="dose-input"><span>Intensidade da fonte (S)</span><div class="input-unit"><input id="sim-strength" type="number" min="0.001" step="0.1" value="8"><b>µSv·m²/h</b></div></label>
        <button id="sim-apply" class="start-button" type="button">Aplicar fonte</button>
        <p class="section-description">Encerre a missão antes de mudar a fonte. Contagens variam com a distância e incluem flutuação estatística.</p>
        </details>
    '''
    html = html.replace('        <button id="start-button"', fields + '\n        <button id="start-button"', 1)
    html = html.replace("</body>", '<script src="/simulation/field.js"></script>\n<script src="/simulation/adapter.js"></script>\n</body>')
    model = {"sensitivity": config.cps_por_usvh, "height_m": config.altura_fonte_m}
    html = html.replace("</head>", '<script>window.ARES_SIMULATION_MODEL = '
                        + json.dumps(model, allow_nan=False) + ';</script>\n</head>')
    html = html.replace("</head>", '<style>.sidebar{overflow-y:auto;grid-template-rows:auto auto auto;align-content:start}</style>\n</head>')

    @app.get("/", response_class=HTMLResponse)
    def panel():
        return html

    @app.get("/simulation/adapter.js")
    def adapter():
        return FileResponse(Path(__file__).with_name("adapter.js"), media_type="application/javascript")

    @app.get("/simulation/field.js")
    def field_script():
        return FileResponse(Path(__file__).with_name("field.js"), media_type="application/javascript")

    return app


if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=8001, log_level="info")
