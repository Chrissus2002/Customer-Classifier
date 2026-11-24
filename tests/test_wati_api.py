#!/usr/bin/env python3
"""
Wati API Test Script
Tests API connection and explores data structure for multi-tenant design.

Run: python test_wati_api.py
"""

import os
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from parent directory (project root)
project_root = Path(__file__).parent.parent  # Go up from app/ to project root
env_path = project_root / '.env'
load_dotenv(dotenv_path=env_path)

print("\n" + "=" * 60)
print(f"🔍 Looking for .env at: {env_path}")
if env_path.exists():
    print("✅ Found .env file")
else:
    print("❌ .env file not found - copy .env.example to .env in project root")

class WatiAPITester:
    def __init__(self):
        self.api_token = os.getenv('WATI_ACCESS_TOKEN', '')
        self.base_url = os.getenv('WATI_ENDPOINT', 'https://live-mt-server.wati.io')

        # Remove tenant-id from URL if present (we'll add it properly)
        if '/wa' not in self.base_url:
            self.base_url = self.base_url.rstrip('/')
        else:
            # Extract base URL without tenant path
            parts = self.base_url.split('/wa')
            self.base_url = parts[0]

        self.headers = {
            'Authorization': self.api_token,
            'Content-Type': 'application/json'
        }
        
        print(f"🔧 Testing Wati API")
        print(f"📡 Base URL: {self.base_url}")
        print(f"🔑 Token: {self.api_token[:10]}...{self.api_token[-4:] if len(self.api_token) > 14 else 'SHORT'}")
        print("-" * 60)

    def test_contacts_endpoint(self):
        """Test contacts endpoint"""
        print("\n👥 Testing Contacts Endpoint...")

        try:
            url = self.base_url + "/api/v1/getContacts/?pageSize=6796"
            response = requests.get(url, headers=self.headers)
            print(f"Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print("✅ Contacts endpoint working!")
                # Analyze structure
                if 'contact_list' in data:
                    contacts = data['contact_list'][:3]  # All contacts
                    print(f"📊 Found {len(data.get('contact_list', []))} total contacts")
                    print(f"Sample contacts structure:")
                    for i, contact in enumerate(contacts):
                        print(f"  Contact {i+1}:")
                        print(contact)
                        print()

                return data
            else:
                print(f"❌ Contacts Error: {response.status_code}")
                print(f"Response: {response.text}")
                return None

        except Exception as e:
            print(f"❌ Contacts Error: {e}")
            return None

    def test_messages_endpoint(self, whatsappNumber, limit=5):
        """Test messages endpoint with recent messages"""
        print(f"\n💬 Testing Messages Endpoint (last {limit} messages)...")

        try:
            # Try to get recent messages
            response = requests.get(
                self.base_url + "/api/v1/getMessages/" + whatsappNumber,
                headers=self.headers,
                params={'limit': limit}
            )

            if response.json()['result'] == False:
                print("Messages Error: " + response.json()['info'])
                return None
            
            print(f"Status: {response.status_code}")
 
            if response.status_code == 200:
                data = response.json()
                print("✅ Messages endpoint working!")

                # Analyze structure
                messages = data.get('messages', data.get('data', []))
                print(f"📊 Found {len(messages)} messages in response")

                if messages:
                    print("Sample message structure:")
                    sample_msg = messages[0]
                    for key, value in sample_msg.items():
                        # Truncate long values
                        if isinstance(value, str) and len(value) > 50:
                            value = value[:50] + "..."
                        print(f"  {key}: {value}")
                    print()

                return data
            else:
                print(f"❌ Messages Error: {response.status_code}")
                print(f"Response: {response.text}")
                return None

        except Exception as e:
            print(f"❌ Messages Error: {e}")
            return None

    def analyze_for_multi_tenant(self, contacts_data, messages_data):
        """Analyze API responses for multi-tenant considerations"""
        print("\n🏗️ Multi-Tenant Analysis...")
        print("-" * 40)

        # Analyze contact structure
        if contacts_data and 'contacts' in contacts_data:
            contact = contacts_data['contacts'][0] if contacts_data['contacts'] else {}
            print("📞 Contact ID Fields Found:")

            for field in ['id', 'waId', 'phone', 'number', 'whatsappNumber']:
                if field in contact:
                    print(f"  ✅ {field}: {contact[field]}")

            print("📊 Contact Metadata Fields:")
            for field in ['name', 'customFields', 'labels', 'createdDateTime']:
                if field in contact:
                    print(f"  ✅ {field}: Present")

        # Analyze message structure
        if messages_data:
            messages = messages_data.get('messages', messages_data.get('data', []))
            if messages:
                message = messages[0]
                print("\n💬 Message ID Fields Found:")

                for field in ['id', 'waId', 'senderName', 'owner', 'type']:
                    if field in message:
                        print(f"  ✅ {field}: {message[field]}")

                print("📝 Message Content Fields:")
                for field in ['text', 'timestamp', 'messageId', 'eventType']:
                    if field in message:
                        print(f"  ✅ {field}: Present")

        # Multi-tenant recommendations
        print("\n🎯 Multi-Tenant Design Recommendations:")
        print("  1. 📱 Use 'waId' or 'phone' for contact phone normalization")
        print("  2. 🔑 Use message 'id' for duplicate detection")
        print("  3. 👤 Use 'senderName' for contact name enrichment")
        print("  4. ⏰ Use 'timestamp' for message ordering")
        print("  5. 🏢 Add tenant_id prefix to all database records")

    def run_full_test(self):
        """Run comprehensive API test"""
        print("🚀 Starting Wati API Comprehensive Test")
        print("=" * 60)

        # Validate environment
        if not self.api_token:
            print("❌ WATI_ACCESS_TOKEN not found in .env file")
            print("💡 Copy .env.example to .env and add your Wati credentials")
            return False
        if not self.base_url:
            print("❌ WATI_ENDPOINT not found in .env file")
            print("💡 Copy .env.example to .env and add your Wati credentials")
            return False

        # Test data endpoints
        contacts_data = self.test_contacts_endpoint()
        messages_data = self.test_messages_endpoint("+528182521126")

        # Analyze for multi-tenant design
        if contacts_data or messages_data:
            self.analyze_for_multi_tenant(contacts_data, messages_data)

        print("\n" + "=" * 60)
        print("🎉 Wati API test completed!")

        if contacts_data and messages_data:
            print("✅ All core endpoints working - ready for multi-tenant implementation")
            return True
        else:
            print("⚠️ Some endpoints had issues - check configuration")
            return False

def main():
    """Main test function"""
    tester = WatiAPITester()
    success = tester.run_full_test()

    if success:
        print("\n🚀 Next steps:")
        print("  1. Review API response structure above")
        print("  2. Implement database schema with tenant_id")
        print("  3. Create multi-tenant Wati client wrapper")
        print("  4. Test webhook ingestion with sample data")
    else:
        print("\n🔧 Fix API connection issues before proceeding")

if __name__ == "__main__":
    main()