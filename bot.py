import os
import threading
import requests
import openai

from flask import Flask, request, jsonify
from dotenv import load_dotenv
from discord import Client, Intents

# Carrega variáveis de ambiente do arquivo .env
load_dotenv()

# -----------------------------
# Lendo variáveis de ambiente
# -----------------------------
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID", "")
PORT = int(os.getenv("PORT", "9000"))

# Configura a API da OpenAI
openai.api_key = OPENAI_API_KEY

# Inicializa Flask
app = Flask(__name__)

# Inicializa o cliente do Discord
intents = Intents.default()
client = Client(intents=intents)

# -----------------------------
# Funções para obter diff e resumir
# -----------------------------
def get_diff_from_github(diff_url: str) -> str:
    """
    Faz uma requisição ao GitHub para obter o diff do Pull Request.
    Retorna o texto bruto do diff.
    """
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3.diff"
    }
    response = requests.get(diff_url, headers=headers)

    if response.status_code != 200:
        print(f"[ERRO] Não foi possível obter o diff. Status code: {response.status_code}")
        return ""

    return response.text

def summarize_diff_with_openai(diff_text: str) -> str:
    """
    Usa a API de ChatCompletion (GPT-3.5 ou GPT-4) para gerar um resumo do diff fornecido.
    """
    if not diff_text.strip():
        return "Não há conteúdo para análise ou o diff está vazio."

    prompt = (
        "Você é um assistente de code review. "
        "Analise o diff a seguir e produza um resumo das mudanças realizadas:\n\n"
        f"{diff_text}\n\n"
        "Por favor, liste as principais alterações e o impacto delas."
    )

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Você é um assistente de code review experiente."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=800
        )
        summary = response["choices"][0]["message"]["content"]
        return summary.strip()
    except Exception as e:
        print("[ERRO] Falha ao chamar a OpenAI:", e)
        return "Falha ao chamar a OpenAI."

def process_pull_request(pr_payload: dict) -> str:
    """
    Extrai o 'diff_url' do payload do PR, obtém o diff via GitHub API e
    solicita à OpenAI um resumo.
    """
    diff_url = pr_payload.get("diff_url")
    if not diff_url:
        return "Pull Request não possui 'diff_url'."

    # 1. Obter o diff
    diff_text = get_diff_from_github(diff_url)

    # 2. Resumir com ChatGPT
    summary = summarize_diff_with_openai(diff_text)
    return summary

# -----------------------------
# Rota para receber o Webhook do GitHub
# -----------------------------
@app.route("/webhook", methods=["POST"])
def github_webhook():
    # Você pode validar a assinatura do webhook aqui (opcional)
    payload = request.json

    # Verificar se é um evento de Pull Request
    if "pull_request" in payload:
        action = payload.get("action")
        pr = payload["pull_request"]

        if action in ["opened", "edited", "synchronize", "reopened"]:
            pr_title = pr["title"]
            pr_url = pr["html_url"]
            base_branch = pr["base"]["ref"]
            head_branch = pr["head"]["ref"]

            # Gera resumo
            summary_result = process_pull_request(pr)

            # Montar mensagem para Discord
            discord_message = (
                f"**Pull Request**: {pr_title}\n"
                f"**Link**: {pr_url}\n"
                f"**Branches**: {base_branch} <- {head_branch}\n\n"
                f"**Resumo das Mudanças**:\n{summary_result}"
            )

            # Enviar mensagem ao Discord
            client.loop.create_task(
                send_discord_message(DISCORD_CHANNEL_ID, discord_message)
            )

    return jsonify({"status": "ok"}), 200

# -----------------------------
# Eventos e funções do bot Discord
# -----------------------------
@client.event
async def on_ready():
    print(f"[INFO] Bot conectado como {client.user}")

async def send_discord_message(channel_id, message):
    channel = client.get_channel(int(channel_id))
    if channel:
        await channel.send(message)
    else:
        print("[ERRO] Canal não encontrado ou ID inválido.")

# -----------------------------
# Execução combinada Flask + Discord
# -----------------------------
def run():
    # Inicia Flask em uma thread separada
    def run_flask():
        app.run(host="0.0.0.0", port=PORT, debug=False)

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Inicia o bot do Discord
    client.run(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    run()