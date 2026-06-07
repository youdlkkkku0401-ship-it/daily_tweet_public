import json
import time
import os
from datetime import datetime
from googleapiclient.discovery import build
import random
import requests
import traceback

# YouTube API設定
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

# ファイルパス
CHANNELS_FILE = "channels.json"
SUBSCRIBER_DATA_FILE = "subscriber_data.json"

def load_channels():
    """channelsファイルを読み込む"""
    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_subscriber_data():
    """前回の登録者数データを読み込む"""
    if os.path.exists(SUBSCRIBER_DATA_FILE):
        with open(SUBSCRIBER_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_updated": "", "channels": {}}

def save_subscriber_data(data):
    """登録者数データを保存"""
    with open(SUBSCRIBER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def chunk_list(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]

#YourubeAPI取得
def get_youtube_subscribers_batch(channel_ids):
    all_results = {}
    
    for chunk in chunk_list(channel_ids, 50):
    
        response = youtube.channels().list(
            part="statistics",
            id=",".join(chunk)
        ).execute()
    
        for item in response["items"]:
            all_results[item["id"]] = int(
                item["statistics"]["subscriberCount"]
            )
    return all_results

#Discord通知
def send_discord_notification(message):
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("Discord webhook not found")
        return
    data = {"content": message}
    try:
        response = requests.post(
            webhook_url,
            json=data,
            timeout=10
        )
    except Exception as e:
        print(f"Discord通知失敗: {e}")

# buffer投稿
def post_to_buffer(post_content):
    token = os.getenv("BUFFER_ACCESS_TOKEN")
    profile_id = os.getenv("BUFFER_PROFILE_ID")
    query = (
        f'mutation {{ createPost(input: {{ '
        f'text: {json.dumps(post_content)} '
        f'channelId: "{profile_id}" '
        f'schedulingType: automatic '
        f'mode: shareNow '
        f'}}) {{ '
        f'... on PostActionSuccess {{ post {{ id text status }} }} '
        f'... on MutationError {{ message }} '
        f'}} }}'
    )
    response = requests.post(
        "https://api.buffer.com/graphql",
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
            },
        json = {"query": query},
        timeout = 30
        )
    response.raise_for_status()
    data = response.json()
    print(data)

    if "errors" in data:
        raise Exception(str(data["errors"]))
    result = data["data"]["createPost"]

    if "message" in result:
        raise Exception(result["message"])
        

#-------------#
#--　メイン　--#
#-------------#
def check_subscriber_increases():
    #データロード
    channels = load_channels()
    subscriber_data = load_subscriber_data()
    channel_ids = list(channels.values())
    current_subscribers_map = get_youtube_subscribers_batch(channel_ids)

    p = 0
    for channel_name, channel_id in channels.items():
        #登録者数読み込み
        current_subscribers = current_subscribers_map.get(channel_id)
        current_subscribers_comma = f"{current_subscribers:,}"
        if current_subscribers is None:
            continue
        
        # 前回の数値を確認
        previous_subscribers = subscriber_data["channels"].get(
            channel_name, {}).get("subscribers", 0)
        
        # 初回取得時はスキップ (今後の追加のために残す)
        if previous_subscribers == 0:
            subscriber_data["channels"][channel_name] = {
                "subscribers": current_subscribers,
                "last_checked": datetime.now().isoformat()
            }
            save_subscriber_data(subscriber_data)
            continue
        
        # 登録者数の増加をチェック
        increase = current_subscribers - previous_subscribers
        
        over2K = increase >= 2000 #2000以上増加
        Kdigit = (current_subscribers // 1000) % 10 #1000の位

        #ツイート条件設定
        post_content = None
        if increase > 1000:
            #10万人突破
            if previous_subscribers // 100000  < current_subscribers // 100000:
                current_million = current_subscribers // 100000 * 10
                post_content = f"#{channel_name} さんが登録者 {current_million}万人 を達成しました！🎉"
    
            #2K以上または奇数の時
            elif (over2K or Kdigit%2 == 1):
            #elif (over2K or current_subscribers % 2000 == 0):
                #投稿差分計算(+***人
                last_post_fan = subscriber_data["channels"].get(channel_name, {}).get("last_post_fan")
                if last_post_fan:
                    post_increase = current_subscribers - last_post_fan
                else:
                    post_increase = increase
    
                #日付計算/*日)
                last_posted_day = subscriber_data["channels"].get(channel_name, {}).get("last_posted_day")
                if last_posted_day:
                    last_posted_dt = datetime.fromisoformat(last_posted_day)
                    delta = datetime.now() - last_posted_dt
                    days = delta.days
                    elapsed_text = f"(+{post_increase}人/{days}日)"
                else:
                    last_count_day = datetime(2026, 5, 8)
                    delta = datetime.now() - last_count_day
                    days = delta.days
                    elapsed_text = f"(+{post_increase}人/{days}日以上)"
                    
                #ツイッター投稿テキスト
                post_content = (f" {channel_name} さん\n"
                                f"登録者数が {current_subscribers_comma}人 に到達しました\n"
                                f"{elapsed_text}")
                post_content += "\u200b" * random.randint(1, 2)
    
            try:
                if post_content:
                    # API呼び出し制限対策4分割
                    if p >= 1:
                        time.sleep(random.randint(20, 50))
                    p += 1
                    print(f"{channel_name} : {current_subscribers}人（＋{increase}人）")
                    
                    ##### Buffer,Discordに送信 #####
                    post_to_buffer(post_content)
                    send_discord_notification(post_content)
                    
                    # データを更新
                    subscriber_data["channels"][channel_name] = {
                        "subscribers": current_subscribers,
                        "last_checked": datetime.now().isoformat(),
                        "last_posted_day": datetime.now().isoformat(),
                        "last_post_fan": current_subscribers
                    }
                else:
                    # データを更新
                    print(f"{channel_name} : 投稿無",flush=True)
                    subscriber_data["channels"][channel_name] = {
                        "subscribers": current_subscribers,
                        "last_checked": datetime.now().isoformat(),
                        "last_posted_day": subscriber_data["channels"].get(channel_name, {}).get("last_posted_day"),
                        "last_post_fan": subscriber_data["channels"].get(channel_name, {}).get("last_post_fan")
                    }
            except Exception as e:
                print(f"Buffer投稿エラー：{e}")
                send_discord_notification(traceback.format_exc())
                raise e
            
            subscriber_data["last_updated"] = datetime.now().isoformat()

    save_subscriber_data(subscriber_data)


if __name__ == "__main__":
    try:
        check_subscriber_increases()
    except Exception:
        error_message = traceback.format_exc()
        print(error_message)
        send_discord_notification(f"実行エラー\n`{error_message[:1500]}`")
        raise
    
