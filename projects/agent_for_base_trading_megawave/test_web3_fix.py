#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple test to verify Web3.py fixes work
"""

import os
import sys
from web3 import Web3, HTTPProvider

# Test Web3 connection and signing
def test_web3_basics():
    print("Testing Web3 basics...")
    
    # Test connection
    w3 = Web3(HTTPProvider("https://mainnet.base.org"))
    if w3.is_connected():
        print("✓ Web3 connection successful")
        
        # Test getting latest block
        try:
            latest_block = w3.eth.get_block("latest")
            print(f"✓ Latest block: {latest_block.number}")
        except Exception as e:
            print(f"✗ Could not get latest block: {e}")
            return False
        
        # Test getting pending block (this might fail)
        try:
            pending_block = w3.eth.get_block("pending")
            print(f"✓ Pending block: {pending_block.number}")
        except Exception as e:
            print(f"✗ Could not get pending block (expected): {e}")
        
        # Test transaction signing
        try:
            # Create a dummy transaction
            tx_dict = {
                "chainId": 8453,
                "nonce": 0,
                "to": "0x0000000000000000000000000000000000000000",
                "from": "0x0000000000000000000000000000000000000000",
                "value": 0,
                "data": "0x",
                "gas": 21000,
                "maxFeePerGas": w3.to_wei(50, "gwei"),
                "maxPriorityFeePerGas": w3.to_wei(2, "gwei"),
                "type": 2,
            }
            
            # Use a dummy private key for testing
            dummy_private_key = "0x" + "0" * 64
            
            signed = w3.eth.account.sign_transaction(tx_dict, dummy_private_key)
            raw_hex = signed.raw_transaction.hex()
            print(f"✓ Transaction signing successful, raw hex length: {len(raw_hex)}")
            
        except Exception as e:
            print(f"✗ Transaction signing failed: {e}")
            return False
        
        return True
    else:
        print("✗ Web3 connection failed")
        return False

def main():
    print("=" * 50)
    print("Web3.py Fix Test")
    print("=" * 50)
    
    if test_web3_basics():
        print("\n✓ All tests passed! The Web3.py fixes should work.")
    else:
        print("\n✗ Some tests failed.")
    
    print("=" * 50)

if __name__ == "__main__":
    main()


