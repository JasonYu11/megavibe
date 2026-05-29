from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import os
import subprocess
def decrypt_key(encrypted_data: str, password: str, salt: str) -> str:

    try:
        # 解码salt并重新生成密钥
        salt_bytes = base64.b64decode(salt)
        key, _ = generate_key(password, salt_bytes)
        
        # 创建Fernet实例进行解密
        f = Fernet(key)
        # 解码加密数据并解密
        decrypted_data = f.decrypt(base64.b64decode(encrypted_data))
        return decrypted_data.decode()
    except Exception as e:
        print(f"解密失败: {e}")
        return None
def generate_key(password: str, salt: bytes = None) -> tuple[bytes, bytes]:
    """从密码生成加密密钥"""
    if salt is None:
        salt = os.urandom(16)
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.b64encode(kdf.derive(password.encode()))
    return key, salt
    
def check_password(word):
    a = 'reg query "HKEY_CURRENT_USER\\Environment" /v python_file'
    result = subprocess.check_output(a, shell=True).decode('utf-8')
    python_file = result.split('REG_SZ')[1].strip()
    b = 'reg query "HKEY_CURRENT_USER\\Environment" /v matlab_1'
    result_salt = subprocess.check_output(b, shell=True).decode('utf-8')
    matlab_1     = result_salt.split('REG_SZ')[1].strip()
    key = decrypt_key(python_file, word,matlab_1)
    return key
