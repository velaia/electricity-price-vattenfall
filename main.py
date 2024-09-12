import requests
import json
import seaborn as sns
import pandas as pd
from matplotlib import pyplot as plt
from datetime import date
from icecream import ic

sns.set_theme()


def main():
    davis_token = get_davis_token()

    response_json = get_current_electricity_price(davis_token)
    ic(response_json)

    # generate plot and save to file
    df = pd.DataFrame([tag["WerteNetto"] for tag in response_json['Result']['Tage']],

                      index=[tag["Datum"] for tag in response_json['Result']['Tage']])
    sns.lineplot(data=df.transpose(), )
    plt.savefig('dual_timeline_plot.png', dpi=300, bbox_inches='tight')

    print(df)


def get_current_electricity_price(davis_token):
    current_date = date.today().strftime("%Y-%m-%d")

    url = "https://davis.vattenfall.de/api/digitalinterface/1.3/Produkt/GetSpotPreis"
    payload = json.dumps({
        "Client": "WEB",
        "Mandant": "VESALES",
        "Timeout": None,
        "ParentLogId": "DBB70020199043F1A1FD07BC75801BD0",
        "TransaktionsId": "f7354700-31b1-41f8-a3cb-d41b2acaf1a4",
        "ReferenzId": "lpProducts",
        "StandVom": None,
        "Sprache": "EN",
        "Priority": "High",
        "Request": {
            "Typ": "60MIN_STROM",
            "Von": current_date,
            "Bis": current_date
        }
    })
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9,de;q=0.8,et;q=0.7,sl;q=0.6,it;q=0.5',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json',
        'DNT': '1',
        'Ocp-Apim-Subscription-Key': 'b2b769e800fb49a7b685c49d050c825d',
        'Origin': 'https://www.vattenfall.de',
        'Pragma': 'no-cache',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'davis-token': davis_token,
        'sec-ch-ua': '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-gpc': '1'
    }
    response = requests.request("POST", url, headers=headers, data=payload)
    response_json = response.json()
    return response_json


def get_davis_token() -> str:
    url = "https://davis.vattenfall.de/api/digitalinterface/1.3/Account/GetTokenAnonym"
    payload = json.dumps({
        "Client": "WEB",
        "Mandant": "VESALES",
        "Timeout": None,
        "StandVom": None,
        "ParentLogId": None,
        "TransaktionsId": "5f1920d2-22d2-4c54-ae0f-a71ecbb9f4eb",
        "Sprache": "DE",
        "ReferenzId": "optin",
        "Priority": None,
        "RequestKeyValues": {},
        "Request": {
            "Tenant": None,
            "Werte": {}
        }
    })
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json',
        'DNT': '1',
        'Ocp-Apim-Subscription-Key': 'b2b769e800fb49a7b685c49d050c825d',
        'Origin': 'https://www.vattenfall.de',
        'Pragma': 'no-cache',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"'
    }
    davis_token = requests.request("POST", url, headers=headers, data=payload).json()['Result']['AccessToken']
    ic(davis_token)
    return davis_token


if __name__ == "__main__":
    main()
