#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnostic script to check OKX API credentials and wallet balance
"""

import os
import sys
import time
import hmac
import json
import base64
import hashlib
import subprocess
from datetime import datetime, timezone
import requests
from web3 import Web3, HTTPProvider

# Import configuration from the main script
from okxswap_buybot_v1 import (
    OKX_API_KEY, OKX_SECRET_KEY, OKX_API_PASSPHRASE, OKX_PROJECT_ID,
    OKX_BASE_URL, WALLET_ADDRESS, EVM_RPC_URL, CHAIN_ID, w3
)

def _iso_ts() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def _sign_headers(method: str, path: str, query: str = "", body: str = "") -> dict:
    ts = _iso_ts()
    to_sign = ts + method.upper() + path + (query or body)
    digest = hmac.new(OKX_SECRET_KEY.encode("utf-8"), to_sign.encode("utf-8"), hashlib.sha256).digest()
    return {
        "Content-Type": "application/json",
        "OK-ACCESS-KEY": OKX_API_KEY,
        "OK-ACCESS-SIGN": base64.b64encode(digest).decode("utf-8"),
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": OKX_API_PASSPHRASE,
        "OK-ACCESS-PROJECT": OKX_PROJECT_ID,
    }

def test_okx_api_credentials():
    """Test OKX API credentials"""
    print("Testing OKX API credentials...")
    
    # Test with a simple API call
    try:
        headers = _sign_headers("GET", "/api/v5/account/balance", query="")
        url = OKX_BASE_URL + "account/balance"
        
        r = requests.get(url, headers=headers, timeout=30)
        
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == "0":
                print("✓ OKX API credentials are valid!")
                return True
            else:
                print(f"✗ OKX API error: {data.get('msg') or data}")
                return False
        else:
            print(f"✗ OKX API HTTP error: {r.status_code} - {r.text}")
            return False
            
    except Exception as e:
        print(f"✗ OKX API test failed: {e}")
        return False

def check_wallet_balance():
    """Check wallet balance and estimate transaction costs"""
    print("\nChecking wallet balance...")
    
    try:
        # Get wallet balance
        balance_wei = w3.eth.get_balance(WALLET_ADDRESS)
        balance_eth = w3.from_wei(balance_wei, 'ether')
        
        print(f"✓ Wallet address: {WALLET_ADDRESS}")
        print(f"✓ Balance: {balance_wei} wei ({balance_eth} ETH)")
        
        # Get current gas price
        try:
            gas_price = w3.eth.gas_price
            print(f"✓ Current gas price: {gas_price} wei ({w3.from_wei(gas_price, 'gwei')} gwei)")
        except Exception as e:
            print(f"✗ Could not get gas price: {e}")
            gas_price = w3.to_wei(50, 'gwei')  # Fallback
        
        # Estimate transaction cost
        estimated_gas = 200000  # Typical swap gas limit
        estimated_cost = estimated_gas * gas_price
        estimated_cost_eth = w3.from_wei(estimated_cost, 'ether')
        
        print(f"✓ Estimated transaction cost: {estimated_cost} wei ({estimated_cost_eth} ETH)")
        
        # Check if sufficient funds
        if balance_wei >= estimated_cost:
            print("✓ Sufficient funds for transaction")
            return True
        else:
            shortfall = estimated_cost - balance_wei
            shortfall_eth = w3.from_wei(shortfall, 'ether')
            print(f"✗ Insufficient funds! Need {shortfall_eth} ETH more")
            return False
            
    except Exception as e:
        print(f"✗ Balance check failed: {e}")
        return False

def suggest_fixes():
    """Suggest fixes for the issues"""
    print("\n" + "=" * 60)
    print("SUGGESTED FIXES")
    print("=" * 60)
    
    print("\n1. OKX API CREDENTIALS ISSUE:")
    print("   - Your OKX API credentials appear to be invalid or expired")
    print("   - You need to:")
    print("     a) Log into your OKX account")
    print("     b) Go to API Management")
    print("     c) Create new API keys with proper permissions")
    print("     d) Update the credentials in the script")
    print("     e) Make sure the API keys have DEX trading permissions")
    
    print("\n2. INSUFFICIENT FUNDS ISSUE:")
    print("   - Your wallet doesn't have enough ETH for the transaction")
    print("   - You need to:")
    print("     a) Add more ETH to your wallet")
    print("     b) Or reduce the swap amount")
    print("     c) Or use a different wallet with more funds")
    
    print("\n3. ALTERNATIVE APPROACH:")
    print("   - Since OKX API is failing, you can:")
    print("     a) Use direct RPC broadcasting (no MEV protection)")
    print("     b) Or fix the OKX credentials first")
    print("     c) Or use a different DEX aggregator")

def test_direct_rpc():
    """Test if direct RPC broadcasting works"""
    print("\nTesting direct RPC broadcasting...")
    
    try:
        # Test basic RPC functionality
        latest_block = w3.eth.get_block("latest")
        print(f"✓ RPC connection works. Latest block: {latest_block.number}")
        
        # Test nonce
        nonce = w3.eth.get_transaction_count(WALLET_ADDRESS, "latest")
        print(f"✓ Current nonce: {nonce}")
        
        return True
    except Exception as e:
        print(f"✗ RPC test failed: {e}")
        return False

def main():
    print("=" * 60)
    print("OKX SWAP BOT DIAGNOSTIC")
    print("=" * 60)
    
    print(f"Chain ID: {CHAIN_ID}")
    print(f"RPC URL: {EVM_RPC_URL}")
    print(f"OKX Base URL: {OKX_BASE_URL}")
    
    # Test OKX API
    okx_works = test_okx_api_credentials()
    
    # Test wallet balance
    balance_ok = check_wallet_balance()
    
    # Test RPC
    rpc_works = test_direct_rpc()
    
    print("\n" + "=" * 60)
    print("DIAGNOSTIC RESULTS")
    print("=" * 60)
    print(f"OKX API: {'✓ Working' if okx_works else '✗ Failed'}")
    print(f"Wallet Balance: {'✓ Sufficient' if balance_ok else '✗ Insufficient'}")
    print(f"RPC Connection: {'✓ Working' if rpc_works else '✗ Failed'}")
    
    # Suggest fixes
    suggest_fixes()
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()


