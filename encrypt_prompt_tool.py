import os
from app.core.prompts import generate_encrypted_env_payload

def main():
    print("==================================================")
    print("DSE Meli Sync - Setup & Encryption Generator Tool")
    print("==================================================")
    
    # Generate key and encrypted prompt
    key, encrypted_prompt = generate_encrypted_env_payload()
    
    print("\n[OK] Gerado Chave de Descriptografia e Payload Criptografado do Prompt Master!")
    print("\nAdicione as seguintes linhas ao seu arquivo `.env`:\n")
    print(f'PROMPT_DECRYPTION_KEY="{key}"')
    print(f'MASTER_PROMPT_ENCRYPTED="{encrypted_prompt}"')
    
    # Proactively check if .env already exists. If not, create it pre-filled
    env_path = ".env"
    if not os.path.exists(env_path):
        print(f"\n[INFO] Arquivo {env_path} nao encontrado. Criando um novo com base no .env.example...")
        if os.path.exists(".env.example"):
            with open(".env.example", "r", encoding="utf-8") as f:
                content = f.read()
            
            # Replace placeholder values
            content = content.replace(
                'PROMPT_DECRYPTION_KEY="your-32-byte-base64-key-here="',
                f'PROMPT_DECRYPTION_KEY="{key}"'
            )
            content = content.replace(
                'MASTER_PROMPT_ENCRYPTED="your-encrypted-master-prompt-hex-or-base64-here"',
                f'MASTER_PROMPT_ENCRYPTED="{encrypted_prompt}"'
            )
            
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("[OK] Arquivo `.env` criado e configurado automaticamente!")
        else:
            print("[WARN] Aviso: .env.example nao foi encontrado. Por favor, crie o arquivo .env manualmente.")
    else:
        print("\n[INFO] Um arquivo `.env` ja existe. Por favor, atualize-o manualmente se necessario.")
        
    print("\n==================================================")

if __name__ == "__main__":
    main()
