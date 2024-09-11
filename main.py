import requests
import json
import seaborn as sns
import pandas as pd
from matplotlib import pyplot as plt
from datetime import date

sns.set_theme()


def main():

    url = "https://davis.vattenfall.de/api/digitalinterface/1.3/Produkt/GetSpotPreis"
    davis_token = 'access.ufu4XeozLP9+8CriHgQIUB+rLYRhcc9uKGe602wAHTSuAMRUsK048NIxuG+U.na1A0jFuEGMu1Kev'

    current_date = date.today().strftime("%Y-%m-%d")

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

    response_json = json.loads(response.text)

    print(response_json)

    df = pd.DataFrame([tag["WerteNetto"] for tag in response_json['Result']['Tage']],

                      index=[tag["Datum"] for tag in response_json['Result']['Tage']])

    sns.lineplot(data=df.transpose(),)

    plt.savefig('dual_timeline_plot.png', dpi=300, bbox_inches='tight')


 
    





if __name__ == "__main__":
    main()
