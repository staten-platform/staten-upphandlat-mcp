#!/usr/bin/env python3
"""Test script to check MCP endpoints."""

import json
import httpx
import asyncio


async def test_endpoints():
    """Test various MCP endpoints to find the correct one."""
    
    base_url = "http://127.0.0.1:8000"
    
    # Test different possible endpoints
    endpoints_to_test = [
        "/mcp",           # Root of mounted app
        "/mcp/",          # Root with trailing slash
        "/mcp/jsonrpc",   # Common JSON-RPC endpoint
        "/mcp/rpc",       # Alternative RPC endpoint
        "/mcp/api",       # Alternative API endpoint
    ]
    
    # Test payload
    test_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "list_tools",
        "params": {}
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        print("Testing MCP endpoints...\n")
        
        for endpoint in endpoints_to_test:
            url = f"{base_url}{endpoint}"
            print(f"Testing: {url}")
            
            try:
                # Test GET request first
                print(f"  GET {url}")
                response = await client.get(url)
                print(f"    Status: {response.status_code}")
                print(f"    Headers: {dict(response.headers)}")
                if response.text:
                    print(f"    Response: {response.text[:200]}...")
                print()
                
                # Test POST request
                print(f"  POST {url}")
                response = await client.post(
                    url,
                    json=test_payload,
                    headers={"Content-Type": "application/json"}
                )
                print(f"    Status: {response.status_code}")
                print(f"    Headers: {dict(response.headers)}")
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        print(f"    JSON Response: {json.dumps(data, indent=2)}")
                        print("    ✅ SUCCESS! This endpoint works.")
                    except Exception as e:
                        print(f"    Response text: {response.text}")
                        print(f"    ❌ JSON parse error: {e}")
                else:
                    print(f"    Response: {response.text}")
                    print(f"    ❌ Failed with status {response.status_code}")
                
            except Exception as e:
                print(f"    ❌ Request failed: {e}")
            
            print("-" * 50)
            print()


if __name__ == "__main__":
    print("Make sure your MCP server is running on http://127.0.0.1:8000")
    print("Then run this script to test endpoints.\n")
    
    asyncio.run(test_endpoints())