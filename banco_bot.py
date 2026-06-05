import discord
from discord.ext import commands
from discord import app_commands
import os
import sqlite3
from datetime import datetime

# Configuração
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='/', intents=intents)

BANK_YELLOW = 0xFFD700
BANK_GREEN = 0x00FF00
BANK_RED = 0xFF0000
BANK_BLUE = 0x00AAFF

# ============ BANCO DE DADOS ============
DB_PATH = 'banco_cbits.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contas (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            saldo INTEGER DEFAULT 1000,
            divida INTEGER DEFAULT 0,
            bloqueado INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            tipo TEXT NOT NULL,
            valor INTEGER NOT NULL,
            descricao TEXT,
            data TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS emprestimos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            valor INTEGER NOT NULL,
            parcelas INTEGER NOT NULL,
            parcelas_pagas INTEGER DEFAULT 0,
            valor_parcela INTEGER NOT NULL,
            status TEXT DEFAULT 'ativo',
            data_emprestimo TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Banco de dados do banco inicializado!")

def get_saldo(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT saldo FROM contas WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 1000

def get_divida(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT divida FROM contas WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

def criar_conta(user_id, username):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO contas (user_id, username, saldo) VALUES (?, ?, 1000)', (user_id, username))
    conn.commit()
    conn.close()

def adicionar_saldo(user_id, valor, descricao=""):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE contas SET saldo = saldo + ? WHERE user_id = ?', (valor, user_id))
    cursor.execute('INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (?, "deposito", ?, ?)', 
                   (user_id, valor, descricao))
    conn.commit()
    novo_saldo = get_saldo(user_id)
    conn.close()
    return novo_saldo

def remover_saldo(user_id, valor, descricao=""):
    saldo_atual = get_saldo(user_id)
    if saldo_atual < valor:
        return False, saldo_atual
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE contas SET saldo = saldo - ? WHERE user_id = ?', (valor, user_id))
    cursor.execute('INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (?, "saque", ?, ?)', 
                   (user_id, valor, descricao))
    conn.commit()
    novo_saldo = get_saldo(user_id)
    conn.close()
    return True, novo_saldo

def transferir(de_user_id, para_user_id, valor):
    if get_saldo(de_user_id) < valor:
        return False, "Saldo insuficiente!"
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('UPDATE contas SET saldo = saldo - ? WHERE user_id = ?', (valor, de_user_id))
    cursor.execute('UPDATE contas SET saldo = saldo + ? WHERE user_id = ?', (valor, para_user_id))
    
    cursor.execute('INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (?, "transferencia_enviada", ?, ?)', 
                   (de_user_id, valor, f"Para {para_user_id}"))
    cursor.execute('INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (?, "transferencia_recebida", ?, ?)', 
                   (para_user_id, valor, f"De {de_user_id}"))
    
    conn.commit()
    conn.close()
    return True, "Transferência realizada!"

def solicitar_emprestimo(user_id, valor, parcelas):
    if valor < 100:
        return False, "Valor mínimo para empréstimo é 100 CBITS!", 0, 0
    if parcelas < 1 or parcelas > 12:
        return False, "Parcelas devem ser entre 1 e 12!", 0, 0
    
    juros = 10
    valor_com_juros = int(valor * (1 + juros/100))
    valor_parcela = valor_com_juros // parcelas
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO emprestimos (user_id, valor, parcelas, valor_parcela) 
        VALUES (?, ?, ?, ?)
    ''', (user_id, valor, parcelas, valor_parcela))
    
    adicionar_saldo(user_id, valor, f"Empréstimo de {valor} CBITS")
    cursor.execute('UPDATE contas SET divida = divida + ? WHERE user_id = ?', (valor_com_juros, user_id))
    
    conn.commit()
    conn.close()
    return True, "Empréstimo aprovado!", valor_com_juros, valor_parcela

def pagar_parcela(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, valor_parcela, parcelas, parcelas_pagas FROM emprestimos WHERE user_id = ? AND status = "ativo" LIMIT 1', (user_id,))
    emprestimo = cursor.fetchone()
    
    if not emprestimo:
        conn.close()
        return False, "Você não tem empréstimos ativos!"
    
    emprestimo_id, valor_parcela, parcelas, parcelas_pagas = emprestimo
    saldo = get_saldo(user_id)
    
    if saldo < valor_parcela:
        conn.close()
        return False, f"Saldo insuficiente! Parcela: {valor_parcela} CBITS"
    
    remover_saldo(user_id, valor_parcela, f"Pagamento de parcela {parcelas_pagas + 1}/{parcelas}")
    cursor.execute('UPDATE contas SET divida = divida - ? WHERE user_id = ?', (valor_parcela, user_id))
    cursor.execute('UPDATE emprestimos SET parcelas_pagas = parcelas_pagas + 1 WHERE id = ?', (emprestimo_id,))
    
    novas_pagas = parcelas_pagas + 1
    
    if novas_pagas >= parcelas:
        cursor.execute('UPDATE emprestimos SET status = "pago" WHERE id = ?', (emprestimo_id,))
        mensagem = f"✅ Empréstimo quitado! Todas as {parcelas} parcelas foram pagas."
    else:
        mensagem = f"✅ Parcela {novas_pagas}/{parcelas} paga! Próxima parcela: {valor_parcela} CBITS"
    
    conn.commit()
    conn.close()
    return True, mensagem

def get_extrato(user_id, limite=10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT tipo, valor, descricao, data FROM transacoes 
        WHERE user_id = ? ORDER BY data DESC LIMIT ?
    ''', (user_id, limite))
    result = cursor.fetchall()
    conn.close()
    return result

def get_ranking(limite=10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT username, saldo FROM contas 
        WHERE saldo > 0 ORDER BY saldo DESC LIMIT ?
    ''', (limite,))
    result = cursor.fetchall()
    conn.close()
    return result

# ============ COMANDOS ============
@bot.event
async def on_ready():
    print(f'🏦 {bot.user} - Banco CBITS está online!')
    init_db()
    await bot.change_presence(activity=discord.Game(name='🏦 Banco CBITS | /banco_ajuda'))
    
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} comandos sincronizados!")
    except Exception as e:
        print(f"Erro: {e}")

@bot.tree.command(name='banco_ajuda', description='🏦 Mostrar todos os comandos')
async def banco_ajuda(interaction: discord.Interaction):
    embed = discord.Embed(
        title='🏦 BANCO CBITS - COMANDOS',
        color=BANK_YELLOW
    )
    embed.add_field(name='💰 /banco_saldo', value='Ver seu saldo', inline=True)
    embed.add_field(name='📥 /banco_depositar', value='Depositar CBITS', inline=True)
    embed.add_field(name='📤 /banco_sacar', value='Sacar CBITS', inline=True)
    embed.add_field(name='🔄 /banco_transferir', value='Transferir para outro', inline=False)
    embed.add_field(name='📊 /banco_extrato', value='Ver últimas transações', inline=True)
    embed.add_field(name='🏆 /banco_ranking', value='Ranking dos mais ricos', inline=True)
    embed.add_field(name='💸 /banco_emprestimo', value='Solicitar empréstimo', inline=False)
    embed.add_field(name='📅 /banco_pagar_parcela', value='Pagar parcela', inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='banco_saldo', description='💰 Ver seu saldo')
async def banco_saldo(interaction: discord.Interaction):
    criar_conta(str(interaction.user.id), interaction.user.name)
    saldo = get_saldo(str(interaction.user.id))
    divida = get_divida(str(interaction.user.id))
    
    embed = discord.Embed(
        title='💰 EXTRATO BANCÁRIO',
        description=f'**{interaction.user.name}**',
        color=BANK_GREEN if saldo > 0 else BANK_RED
    )
    embed.add_field(name='💵 Saldo', value=f'**{saldo} CBITS**', inline=True)
    embed.add_field(name='📉 Dívida', value=f'**{divida} CBITS**', inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='banco_depositar', description='📥 Depositar CBITS')
@app_commands.describe(valor="Quantidade para depositar")
async def banco_depositar(interaction: discord.Interaction, valor: int):
    if valor <= 0:
        await interaction.response.send_message('❌ Valor inválido!', ephemeral=True)
        return
    
    criar_conta(str(interaction.user.id), interaction.user.name)
    saldo_antes = get_saldo(str(interaction.user.id))
    novo_saldo = adicionar_saldo(str(interaction.user.id), valor, "Depósito voluntário")
    
    embed = discord.Embed(
        title='✅ DEPÓSITO REALIZADO!',
        color=BANK_GREEN
    )
    embed.add_field(name='💰 Saldo anterior', value=f'{saldo_antes} CBITS', inline=True)
    embed.add_field(name='💰 Novo saldo', value=f'{novo_saldo} CBITS', inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='banco_sacar', description='📤 Sacar CBITS')
@app_commands.describe(valor="Quantidade para sacar")
async def banco_sacar(interaction: discord.Interaction, valor: int):
    if valor <= 0:
        await interaction.response.send_message('❌ Valor inválido!', ephemeral=True)
        return
    
    criar_conta(str(interaction.user.id), interaction.user.name)
    saldo_antes = get_saldo(str(interaction.user.id))
    
    sucesso, novo_saldo = remover_saldo(str(interaction.user.id), valor, "Saque normal")
    
    if not sucesso:
        await interaction.response.send_message(f'❌ Saldo insuficiente! Você tem {saldo_antes} CBITS', ephemeral=True)
        return
    
    embed = discord.Embed(
        title='✅ SAQUE REALIZADO!',
        color=BANK_GREEN
    )
    embed.add_field(name='💰 Saldo anterior', value=f'{saldo_antes} CBITS', inline=True)
    embed.add_field(name='💰 Novo saldo', value=f'{novo_saldo} CBITS', inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='banco_transferir', description='🔄 Transferir CBITS')
@app_commands.describe(usuario="Destinatário", valor="Quantidade")
async def banco_transferir(interaction: discord.Interaction, usuario: discord.User, valor: int):
    if valor <= 0:
        await interaction.response.send_message('❌ Valor inválido!', ephemeral=True)
        return
    
    if usuario.id == interaction.user.id:
        await interaction.response.send_message('❌ Não pode transferir para si mesmo!', ephemeral=True)
        return
    
    criar_conta(str(interaction.user.id), interaction.user.name)
    criar_conta(str(usuario.id), usuario.name)
    
    sucesso, mensagem = transferir(str(interaction.user.id), str(usuario.id), valor)
    
    if not sucesso:
        await interaction.response.send_message(f'❌ {mensagem}', ephemeral=True)
        return
    
    embed = discord.Embed(
        title='✅ TRANSFERÊNCIA REALIZADA!',
        description=f'**{valor} CBITS** transferidos para {usuario.mention}',
        color=BANK_GREEN
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='banco_extrato', description='📊 Ver últimas transações')
async def banco_extrato(interaction: discord.Interaction):
    criar_conta(str(interaction.user.id), interaction.user.name)
    transacoes = get_extrato(str(interaction.user.id), 10)
    
    if not transacoes:
        await interaction.response.send_message('📭 Nenhuma transação.', ephemeral=True)
        return
    
    embed = discord.Embed(
        title='📊 ÚLTIMAS TRANSAÇÕES',
        description=f'**{interaction.user.name}**',
        color=BANK_BLUE
    )
    
    for t in transacoes:
        tipo, valor, desc, data = t
        emoji = "📥" if "deposito" in tipo else "📤" if "saque" in tipo else "🔄"
        embed.add_field(
            name=f'{emoji} {tipo.upper()}',
            value=f'Valor: **{valor} CBITS**\n{desc}\n📅 {data[:10]}',
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='banco_ranking', description='🏆 Ranking dos mais ricos')
async def banco_ranking(interaction: discord.Interaction):
    ranking = get_ranking(10)
    
    if not ranking:
        await interaction.response.send_message('📭 Ninguém com saldo positivo.', ephemeral=True)
        return
    
    embed = discord.Embed(title='🏆 RANKING CBITS', color=BANK_YELLOW)
    
    for i, (username, saldo) in enumerate(ranking, 1):
        medalha = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}º"
        embed.add_field(name=f'{medalha} {username}', value=f'💰 {saldo} CBITS', inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='banco_emprestimo', description='💸 Solicitar empréstimo')
@app_commands.describe(valor="Valor desejado", parcelas="Número de parcelas (1-12)")
async def banco_emprestimo(interaction: discord.Interaction, valor: int, parcelas: int):
    criar_conta(str(interaction.user.id), interaction.user.name)
    sucesso, mensagem, valor_com_juros, valor_parcela = solicitar_emprestimo(str(interaction.user.id), valor, parcelas)
    
    if not sucesso:
        await interaction.response.send_message(f'❌ {mensagem}', ephemeral=True)
        return
    
    saldo_novo = get_saldo(str(interaction.user.id))
    
    embed = discord.Embed(
        title='✅ EMPRÉSTIMO APROVADO!',
        color=BANK_GREEN
    )
    embed.add_field(name='💰 Valor com juros', value=f'{valor_com_juros} CBITS', inline=True)
    embed.add_field(name='📅 Parcelas', value=f'{parcelas}x de {valor_parcela} CBITS', inline=True)
    embed.add_field(name='💰 Saldo agora', value=f'{saldo_novo} CBITS', inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='banco_pagar_parcela', description='📅 Pagar parcela do empréstimo')
async def banco_pagar_parcela(interaction: discord.Interaction):
    criar_conta(str(interaction.user.id), interaction.user.name)
    sucesso, mensagem = pagar_parcela(str(interaction.user.id))
    
    if not sucesso:
        await interaction.response.send_message(f'❌ {mensagem}', ephemeral=True)
        return
    
    saldo_novo = get_saldo(str(interaction.user.id))
    embed = discord.Embed(title='✅ PARCELA PAGA!', description=mensagem, color=BANK_GREEN)
    embed.add_field(name='💰 Saldo atual', value=f'{saldo_novo} CBITS', inline=True)
    await interaction.response.send_message(embed=embed)

# ============ INICIAR ============
TOKEN = os.getenv('DISCORD_TOKEN_BANCO')

if not TOKEN:
    TOKEN = input("Cole o token do bot do banco: ").strip()

if not TOKEN:
    print("❌ Token não fornecido!")
    exit()

print("🟡 Iniciando Banco CBITS...")
bot.run(TOKEN)