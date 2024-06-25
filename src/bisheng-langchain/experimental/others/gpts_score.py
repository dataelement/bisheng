import json
import argparse
import datetime
import calendar
import os
from datetime import datetime, timedelta
import re

# 创建解析器
parser = argparse.ArgumentParser(description="Example script to parse command line arguments")

# 添加命令行参数
parser.add_argument("--time", help="Specify the time in YYYYMMDD format")

# 解析命令行参数
args = parser.parse_args()

# 从命令行参数中获取时间   
time_str = args.time


def parse_date(input_str):
    try:
        # Parse the input string into a datetime object
        date_obj = datetime.strptime(input_str, '%Y%m%d')
        # Get today's date
        today_date = datetime.today().date()
        # Create a new datetime object with the date part from the input and time part from today
        output_date = datetime.combine(date_obj.date(), datetime.today().time())
        return output_date
    except ValueError:
        return "Invalid date format"


def get_date_day_month_year(input_str,currenttime):
    # Extract the years, months, and days from the input string
    match = re.match(r'today(-\d+年)?(-\d+个月)?(-\d+天)?', input_str)
    if match:
        years = -int(match.group(1)[:-1]) if match.group(1) else 0
        months = -int(match.group(2)[:-2]) if match.group(2) else 0
        days = -int(match.group(3)[:-1]) if match.group(3) else 0
    # else:
    #     return "Invalid input"

    # Get today's date
    today = currenttime

    # Calculate the date based on years, months, and days
    if days != 0:
        new_date = today - timedelta(days=365 * years) - timedelta(days=30 * months) - timedelta(days=days)
    else:
        if months != 0:
            if today.month-months >= 0:
                new_date = today.replace(year=today.year - years, month=today.month-months, day=today.day-days)
            else:
                new_date = today.replace(year=today.year - years-1, month=today.month-months+12, day=today.day-days)
        else:
            new_date = today.replace(year=today.year - years, month=today.month, day=today.day-days)

    formatted_date = []
    formatted_date.append(new_date.strftime("%d %B %Y"))
    formatted_date.append(new_date.strftime("%Y年%m月%d日"))
    formatted_date.append(new_date.strftime("%Y-%m-%d"))

    return formatted_date


def get_date_day_month_year_whataverday(input_str,currenttime):
    # Extract the years, months, and days from the input string
    match = re.match(r'today(-\d+年)?(-\d+个月)?(-\d+天)?', input_str)
    if match:
        years = -int(match.group(1)[:-1]) if match.group(1) else 0
        months = -int(match.group(2)[:-2]) if match.group(2) else 0
        days = -int(match.group(3)[:-1]) if match.group(3) else 0
    # else:
    #     return "Invalid input"

    # Get today's date
    today = currenttime

    # Calculate the date based on years, months, and days
    new_date = today - timedelta(days=365 * years) - timedelta(days=30 * months) - timedelta(days=days)

    # Adjust for leap years
    leap_years = 0
    for year in range(today.year - years, today.year - years + 1):
        if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
            if 2 <= today.month - months <= 12:
                leap_years += 1

    new_date -= timedelta(days=leap_years)
    formatted_date = []
    formatted_date.append(new_date.strftime("%d %B %Y"))
    formatted_date.append(new_date.strftime("%Y年%m月%d日"))
    formatted_date.append(new_date.strftime("%Y-%m-%d"))

    return formatted_date


currenttime = parse_date(time_str)
print(currenttime)
# 读取 JSON 文件
with open('/home/gulixin/GPTS/GT/gt_ignore_time.json', 'r', encoding='utf-8') as f:
    gt_data = json.load(f)

# 解析数据
allgt = []
slicelen = []
countsingle = 0
for item in gt_data['data']:
    dataset_id = item['id']
    # print(f"数据集标识符: {dataset_id}")

    for record in item['times']:
        if 'tool_calls' in record:
            for tool_call in record['tool_calls']:
                
                temp = {}
                operation_name = tool_call['name']
                if tool_call['arguments']:
                    arguments = tool_call['arguments']
                else:
                    arguments = None

                if 'other' in tool_call:
                    temp["isother"] = '1'
                    temp["other"] = tool_call['other']
                temp["name"] = operation_name
                temp["arg"] = arguments 
                allgt.append(temp)
                # print(f"操作名称: {operation_name}")
                # print(f"参数: {arguments}")
        elif 'content' in record:
            content = record['content']
            # print(f"内容/结果: {content}")
            temp = {}
            temp['content'] = content
            if "valid" in record:
                temp['valid'] = record["valid"]
            allgt.append(temp)

        countsingle += 1
    slicelen.append(countsingle)
print(len(allgt))
print(allgt)


statementsingle = []
dirname = "/home/gulixin/GPTS/GPT4-result"
for item in gt_data['data']:
    file_name = item['id']
    jsonname = os.path.join(dirname, file_name)
    print("#####################",file_name,"#####################")
    with open(jsonname, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 解析数据
    for message in data['messages']:
        if message.get('role') == 'assistant':
            # print(message)
            tempstring = ''
            if 'tool_calls' in message and message['content'] == None:
                for tool_call in message['tool_calls']:
                    name = tool_call['function']['name']
                    arguments = tool_call['function']['arguments']
                    tempstring += name
                    tempstring += arguments
                    print(f"操作名称: {name}")
                    print(f"参数: {arguments}")
            elif 'tool_calls' in message and message['content'] != None:
                content = message['content']
                tempstring += content
                print("content:",content) 
            statementsingle.append(tempstring)


tt = 0
allstatement = 0
hitstatement = 0
score = 0
requestscore = []
with open("/home/gulixin/GPTS/test-data/func_call_ageent_pred_local_command_r_plus_v2.jsonl") as json_file:
    for line in json_file.readlines():
    # for line in statementsingle:
        # 解析JSON字符串为Python字典
        singleall = 0
        singlehit = 0
        allmessage = line
        # print(str(allmessage))
        singlekeyword = []
        gtt = allgt[tt]
        if 'valid' in gtt:
            continue
        
        if 'isother' in gtt:
            singlelen = len(gtt['other'])
            alllen = singlelen + 1
            allstatement += alllen
            singleall += alllen
            keywordunion = []
            
            for words in gtt['other']:
                for word in words:
                    if 'today' in word:
                        tempdateinfo = get_date_day_month_year(word,currenttime)
                        for changedateinfo in tempdateinfo:
                            keywordunion.append(changedateinfo)
                        # singleall -= 2
                        # allstatement -= 2
                    else:
                        keywordunion.append(word)
                        
            keywordunion.append(gtt["name"])
            
            for words in gtt['arg']:
                if words == '':
                    continue
                if 'today' in words:
                    tempdateinfo = get_date_day_month_year(words,currenttime)
                    for changedateinfo in tempdateinfo:
                        keywordunion.append(changedateinfo)
                    # singleall -= 2
                    # allstatement -= 2
                else:
                    keywordunion.append(words)
                    
            for keyword in keywordunion:
                
                if keyword in str(allmessage).replace(',',''):
                    singlehit += 1
                    hitstatement += 1
            if singlehit > singleall:
                singlehit = singleall
            # if singleall < 0:
            #     singleall 
            print("第",tt,"次分数",singlehit/alllen)
            print("keyword:", keywordunion,"         ","message",allmessage)
            tt += 1
            score += singlehit/singleall
            requestscore.append(singlehit/singleall)
            continue
        
        for i in gtt:
            if isinstance(gtt[i],list):
                for j in gtt[i]:
                    keyword = j
                    keyword = str(keyword).replace('[','')
                    keyword = str(keyword).replace(']','')
                    keyword = str(keyword).replace("'",'')
                    keyword = str(keyword).replace("{",'')
                    keyword = str(keyword).replace("}",'')
                    if keyword == '':
                        continue
                    if 'today' in keyword:
                        tempdateinfo = get_date_day_month_year(keyword,currenttime)
                        for changedateinfo in tempdateinfo:
                            singlekeyword.append(changedateinfo)
                        # singleall -= 2
                        # allstatement -= 2
                    else:
                        singlekeyword.append(keyword)
                    
                    allstatement += 1
                    singleall += 1
                for keyword in singlekeyword:
                    if keyword in str(allmessage).replace(',',''):
                        hitstatement += 1
                        singlehit += 1
                if singlehit > singleall:
                    singlehit = singleall
                    
            else:
                keyword = gtt[i]
                keyword = str(keyword).replace('[','')
                keyword = str(keyword).replace(']','')
                keyword = str(keyword).replace("'",'')
                keyword = str(keyword).replace("{",'')
                keyword = str(keyword).replace("}",'')
                if 'today' in keyword:
                    tempdateinfo = get_date_day_month_year(keyword,currenttime)
                    for changedateinfo in tempdateinfo:
                        singlekeyword.append(changedateinfo)
                    # singleall -= 2
                    # allstatement -= 2
                else:
                    singlekeyword.append(keyword)

                if keyword in str(allmessage).replace(',',''):
                    hitstatement += 1
                    singlehit += 1
                
                allstatement += 1
                singleall += 1
            
        if singleall == 0:
            singlehit = 1
            singleall = 1
        
        print("第",tt,"次分数",singlehit/singleall)
        print("keyword:",singlekeyword,"         ","message",allmessage)
        tt += 1
        score += singlehit/singleall
        requestscore.append(singlehit/singleall)

print(allstatement,hitstatement)
print(score/33)
print(slicelen)     
print(slicelen)     
count  = 0 
for i in requestscore:
    if i == 1:
       count += 1
print(count) 
print(count/33)
