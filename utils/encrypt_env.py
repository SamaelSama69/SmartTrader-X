"""
Encrypt/decrypt .env file using cryptography.fernet
"""
from cryptography.fernet import Fernet
from pathlib import Path
import os
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def generate_key():
    """Generate a new encryption key"""
    return Fernet.generate_key()

def encrypt_env(master_password: str, env_file: str = ".env", output_file: str = ".env.encrypted"):
    """Encrypt .env file"""
    # Derive key from password
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(master_password.encode()))

    fernet = Fernet(key)

    # Read and encrypt
    with open(env_file, 'rb') as f:
        data = f.read()

    encrypted = fernet.encrypt(data)

    with open(output_file, 'wb') as f:
        f.write(salt + encrypted)

    print(f"Encrypted {env_file} to {output_file}")

def decrypt_env(master_password: str, encrypted_file: str = ".env.encrypted", output_file: str = ".env"):
    """Decrypt .env file"""
    with open(encrypted_file, 'rb') as f:
        salt = f.read(16)
        encrypted = f.read()

    # Derive key
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(master_password.encode()))

    fernet = Fernet(key)
    decrypted = fernet.decrypt(encrypted)

    with open(output_file, 'wb') as f:
        f.write(decrypted)

    print(f"Decrypted {encrypted_file} to {output_file}")