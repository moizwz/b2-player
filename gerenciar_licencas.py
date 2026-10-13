import sqlite3
import os
from datetime import datetime

# Caminho absoluto para garantir que o script ache o banco correto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "database.db")

def adicionar_ou_atualizar_licenca(mac, nome_cliente, data_expiracao):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Garante que a tabela existe
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS licenses (
            mac TEXT PRIMARY KEY,
            name TEXT,
            expiry_date TEXT,
            status TEXT
        )
    ''')
    
    # Insere ou atualiza o MAC com status ativo
    cursor.execute('''
        INSERT OR REPLACE INTO licenses (mac, name, expiry_date, status)
        VALUES (?, ?, ?, 'active')
    ''', (mac.upper(), nome_cliente, data_expiracao))
    
    conn.commit()
    conn.close()
    print(f"✅ Sucesso! Licença ativada para {nome_cliente} (MAC: {mac.upper()}) até {data_expiracao}.")

def listar_licencas():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT mac, name, expiry_date, status FROM licenses")
    rows = cursor.fetchall()
    conn.close()
    
    print("\n📋 --- LISTA DE CLIENTES LICENCIADOS ---")
    if not rows:
        print("Nenhuma licença cadastrada ainda.")
    for row in rows:
        print(f"MAC: {row[0]} | Nome: {row[1]} | Validade: {row[2]} | Status: {row[3]}")
    print("-" * 40)

if __name__ == "__main__":
    while True:
        print("\n--- PAINEL DE CONTROLE DE LICENÇAS B2 PLAYER ---")
        print("1. Adicionar ou Renovar Licença")
        print("2. Listar Clientes Licenciados")
        print("3. Sair")
        
        opcao = input("Escolha uma opção (1-3): ").strip()
        
        if opcao == "1":
            mac_input = input("Digite o MAC Address do dispositivo (ex: B2:1A:2B:3C:4D:5E): ").strip()
            nome_input = input("Nome do Cliente: ").strip()
            exp_input = input("Data de Expiração (AAAA-MM-DD, ex: 2027-12-31): ").strip()
            
            if mac_input and nome_input and exp_input:
                adicionar_ou_atualizar_licenca(mac_input, nome_input, exp_input)
            else:
                print("❌ Todos os campos são obrigatórios!")
                
        elif opcao == "2":
            listar_licencas()
            
        elif opcao == "3":
            print("A sair...")
            break
        else:
            print("❌ Opção inválida.")