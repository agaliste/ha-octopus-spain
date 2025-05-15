from datetime import datetime, timedelta

from python_graphql_client import GraphqlClient

GRAPH_QL_ENDPOINT = "https://api.oees-kraken.energy/v1/graphql/"
SOLAR_WALLET_LEDGER = "SOLAR_WALLET_LEDGER"
ELECTRICITY_LEDGER = "SPAIN_ELECTRICITY_LEDGER"


class OctopusSpain:
    def __init__(self, email, password):
        self._email = email
        self._password = password
        self._token = None

    async def login(self):
        mutation = """
           mutation obtainKrakenToken($input: ObtainJSONWebTokenInput!) {
              obtainKrakenToken(input: $input) {
                token
              }
            }
        """
        variables = {"input": {"email": self._email, "password": self._password}}

        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT)
        response = await client.execute_async(mutation, variables)

        if "errors" in response:
            return False

        self._token = response["data"]["obtainKrakenToken"]["token"]
        return True

    async def accounts(self):
        query = """
             query getAccountNames{
                viewer {
                    accounts {
                        ... on Account {
                            number
                            properties {
                                id
                            }
                        }
                    }
                }
            }
            """

        headers = {"authorization": self._token}
        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)
        response = await client.execute_async(query)

        accounts_data = response["data"]["viewer"]["accounts"]
        result = []
        for account in accounts_data:
            account_number = account["number"]
            properties = account.get("properties", [])
            property_ids = [prop["id"] for prop in properties] if properties else []
            result.append({
                "account_number": account_number,
                "property_ids": property_ids
            })
        return result

    async def account(self, account: str):
        query = """
            query ($account: String!) {
              accountBillingInfo(accountNumber: $account) {
                ledgers {
                  ledgerType
                  statementsWithDetails(first: 1) {
                    edges {
                      node {
                        amount
                        consumptionStartDate
                        consumptionEndDate
                        issuedDate
                      }
                    }
                  }
                  balance
                }
              }
            }
        """
        headers = {"authorization": self._token}
        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)
        response = await client.execute_async(query, {"account": account})
        ledgers = response["data"]["accountBillingInfo"]["ledgers"]
        electricity = next(filter(lambda x: x['ledgerType'] == ELECTRICITY_LEDGER, ledgers), None)
        solar_wallet = next(filter(lambda x: x['ledgerType'] == SOLAR_WALLET_LEDGER, ledgers), {'balance': 0})

        if not electricity:
            raise Exception("Electricity ledger not found")

        invoices = electricity["statementsWithDetails"]["edges"]

        if len(invoices) == 0:
            return {
                'solar_wallet': None,
                'last_invoice': {
                    'amount': None,
                    'issued': None,
                    'start': None,
                    'end': None
                }
            }

        invoice = invoices[0]["node"]

        # Los timedelta son bastante chapuzas, habrá que arreglarlo
        return {
            "solar_wallet": (float(solar_wallet["balance"]) / 100),
            "octopus_credit": (float(electricity["balance"]) / 100),
            "last_invoice": {
                "amount": invoice["amount"] if invoice["amount"] else 0,
                "issued": datetime.fromisoformat(invoice["issuedDate"]).date(),
                "start": (datetime.fromisoformat(invoice["consumptionStartDate"]) + timedelta(hours=2)).date(),
                "end": (datetime.fromisoformat(invoice["consumptionEndDate"]) - timedelta(seconds=1)).date(),
            },
        }
        
    async def get_consumption(self, property_id, start_at, end_at, timezone="Europe/Madrid", first=100):
        """
        Fetch consumption data for a specific property within a date range.
        
        Args:
            property_id: The ID of the property to get consumption for
            start_at: Start datetime in ISO format
            end_at: End datetime in ISO format
            timezone: Timezone string (default: "Europe/Madrid")
            first: Number of records to fetch (default: 100)
            
        Returns:
            Consumption data
        """
        query = """
            query getAccountMeasurements($propertyId: ID!, $first: Int!, $utilityFilters: [UtilityFiltersInput!], $startAt: DateTime, $endAt: DateTime, $timezone: String) {
              property(id: $propertyId) {
                measurements(
                  first: $first
                  utilityFilters: $utilityFilters
                  startAt: $startAt
                  endAt: $endAt
                  timezone: $timezone
                ) {
                  edges {
                    node {
                      value
                      unit
                      ... on IntervalMeasurementType {
                        startAt
                        endAt
                        durationInSeconds
                      }
                      metaData {
                        statistics {
                          costExclTax {
                            pricePerUnit {
                              amount
                            }
                            costCurrency
                            estimatedAmount
                          }
                          costInclTax {
                            costCurrency
                            estimatedAmount
                          }
                          value
                          description
                          label
                          type
                        }
                      }
                    }
                  }
                }
              }
            }
        """
        
        variables = {
            "propertyId": property_id,
            "first": first,
            "startAt": start_at,
            "endAt": end_at,
            "timezone": timezone,
            "utilityFilters": [
                {
                    "electricityFilters": {
                        "readingDirection": "CONSUMPTION",
                        "readingFrequencyType": "HOUR_INTERVAL"
                    }
                }
            ]
        }
        
        headers = {"authorization": self._token}
        client = GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)
        response = await client.execute_async(query, variables)
        
        if "errors" in response:
            return {"error": response["errors"]}
            
        return response["data"]["property"]["measurements"]["edges"]
