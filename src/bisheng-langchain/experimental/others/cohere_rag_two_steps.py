import cohere
import json
import pandas as pd
from langchain_text_splitters import RecursiveCharacterTextSplitter
import re 

# api-key setting
co_api_key = ""
co = cohere.Client(co_api_key)

# cohere保存中间的rag结果
coheredocall = []
cohereciaall = []

# 回答的结果，01是判断是否有答案，source是保存源的位置
ans_01 = []
ans_source = []

# 保存错误信息
wronginformation = []

# 保存所有的源信息
sourcecollection = []

# 保存源的长度，作为统计信息
sourcelencollection = []

# cohere rag preamble
preamble = """
## Task & Context
----> 你是一个可靠的单一文件问题回答助理。你会收到一段文本，你会被要求根据文本内容回答相应的问题，如果上下文中没有答案，你必须回答不知道。如果问题是是否问题，你需要先回答分析内容和步骤，给出原因解释，再回答是否。 <----
## Style Guide
----> 你必须遵循以下规则
1. 如果有答案，你只需要回答答案就行，不能回答其他的内容。
2. 关于定位文档，你必须定位答案的位置。比如，乙方是xx，你只需要定位xx的位置，而不是定位乙方的位置。

你只需要返回问题的答案  <----
"""

# cohere QA 的startmessage和endmessage
startmessage = '''
你是一个可靠的单一文件问题回答助理。你会收到一段文本，你需要根据文本内容回答相应的问题，如果问到你是否问题，你必须给出回答是否的原因和分析，必须有详细的分析。
你必须遵循以下规则:
1. 如果有答案，你只需要回答答案就行。
2. 如果问题是是否问题，你需要先回答具体的分析，给出原因解释，再回答是否。

下面是你收到的文本：
上下文：

'''

endmessage = '''


你需要详细的给出回答问题的分析和原因，根据上下文，回答问题：
'''

# 问题excel的文件
df = pd.read_excel('/home/jingwangyuan/work/data/finance_report_data_100.xlsx')

# 源文件的位置
txtlo = "/home/public/rag_benchmark_finance_report/金融年报财报的来源文件/"
filename1 = df['来源文件']
first_column = df['问题'] 

# 所有的回答
allanswer = []


# 拆分函数
def chunksplit(filename,location):
    txtname = location + filename
    with open(txtname) as f:
        alldata = f.read()
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=100,
        length_function=len,
        is_separator_regex=False,
        separators=["\n\n"],
    )    
    texts = text_splitter.create_documents([alldata])
    return texts
    

# 控制chunk的长度
def chunklenstrict(texts):
    splittextchunk = []
    chunkstrict = []
    templenchunk = 0
    for i in range(len(texts)):
        element = {}
        element["title"] = str(i)
        element["snippet"] = texts[i].page_content
        if templenchunk + len(str(element)) > 80000:
            chunkstrict.append(splittextchunk)
            splittextchunk = []
            templenchunk = 0
        else:
            splittextchunk.append(element)
            templenchunk += len(str(element))
    chunkstrict.append(splittextchunk)
    return chunkstrict


# 保存doc和cia信息
def savedocandcia(filename1,document_cohere,citations_cohere,coheredocall,cohereciaall):
    docdic = {}
    ciadic = {}
    docdic['filename'] = filename1[fileindex]
    docdic['doc'] = str(document_cohere) 
    ciadic['filename'] = filename1[fileindex]
    ciadic['cia'] = str(citations_cohere)
    coheredocall.append(docdic)
    cohereciaall.append(ciadic)
    return coheredocall,cohereciaall
    

# cohere rag 结果生成
def cohererag(chunkstrict,texts,co,question,ans_01,ans_source,coheredocall,cohereciaall):
    for ii in range(len(chunkstrict)):
        content = chunkstrict[ii]
        result = co.chat(
            model="command-r-plus",
            message=question,
            documents=content,
            temperature=0.01,
            preamble=preamble
        ) 
        text_cohere = result.text
        citations_cohere = result.citations
        document_cohere = result.documents
        print("text: ",text_cohere,type(text_cohere))
        print("citations: ",citations_cohere,type(citations_cohere))
        print("documents: ",document_cohere,type(document_cohere))
        
        # save rag information
        coheredocall,cohereciaall = savedocandcia(filename1,document_cohere,citations_cohere,coheredocall,cohereciaall)
        
        temp = []
        if document_cohere:
            for doccitation in document_cohere:
                alldocid = doccitation['title']
                temp.append(alldocid)
            
            ans_01.append(1)
            ans_source.append(temp)
            
        else:
            ans_01.append(0)
            ans_source.append([])
        print("最终结果",ans_01)
        print(ans_source)
    return ans_source,ans_01
    

# message generte
def messagegeneration(ans_source,texts,wronginformation,islimit,limitchunknumber,limitalllen,title):
    templenchunk = 0
    allmessage = ''
    for i in ans_source:
        if i != []:
            if islimit:
                if len(i) > limitchunknumber:
                    i = i[:limitchunknumber]

            for index in i:
                try:
                    
                    templenchunk += len(texts[int(index)].page_content)
                    if templenchunk < limitalllen:
                        allmessage += title + '\n' + texts[int(index)].page_content
                        allmessage += "\n\n"
                    else:
                        break
                except:
                    wro = {}
                    wro["text"] = index
                    wro["file"] = fileindex
                    wronginformation.append(wro)
    print(allmessage)
    
    print("总长度:", templenchunk)
    return allmessage,wronginformation,templenchunk
    

# rag answer
def cohereanswer(co,finalmessage,ans_01,ans_source,allanswer):
    resultallquestion = co.chat(
            model="command-r-plus",
            message=finalmessage,
            temperature=0.01,
    )    
    text_cohere = resultallquestion.text
    citations_cohere = resultallquestion.citations
    document_cohere = resultallquestion.documents
    print("text: ",text_cohere,type(text_cohere))
    print("citations: ",citations_cohere,type(citations_cohere))
    print("documents: ",document_cohere,type(document_cohere))
    ans_01 = []
    ans_source = []
    if document_cohere:
        for i in document_cohere:
            # print("原始位置段落：",i["title"])
            temp.append(i["title"])
        ans_01.append(1)
        ans_source.append(temp)
    else:
        ans_01.append(0)
        ans_source.append([])
    print("单个问题最终结果",ans_01)
    print(ans_source)
    allanswer.append(text_cohere)
    return allanswer


def jsonloaddoc(filenamejson,whetherrepeatset,repeattimes):
    with open(filenamejson) as fp:
        data = fp.read()
    # print(data)
    jsondata = json.loads(data)
    # print(type(jsondata),len(jsondata))
    alldata = {}
    for info in jsondata:
        filename = info["filename"]

        # print(docs)
        # docs = json.loads(info["doc"], strict=False)
        # print(type(docs))
        if filename not in alldata:
            alldata[filename] = {}
            alldata[filename]["filename"] = filename
            alldata[filename]["text"] = ''
            alldata[filename]["index"] = []
        # print(info["doc"])
        if info["doc"] == 'None':
            print(11111111111)
            continue
        else:

            tempdocs = info["doc"]
            tempdocs = re.sub(r"(?<='snippet': \")[^\"]*?(?=\")", lambda x: "'" + x.group(0).replace("'", "") + "'", tempdocs)
            tempdocs = tempdocs.replace("'snippet': \"","'snippet': '")
            tempdocs = tempdocs.replace("\", 'title'","\', 'title'")
            tempdocs = tempdocs.replace("''","'")
            tempdocs = tempdocs.replace("'', 'title'","', 'title'")
            tempdocs = tempdocs.replace('"','')
            tempdocs = tempdocs.replace('“','')
            tempdocs = tempdocs.replace('”','')
        # print(tempdocs)
            docs = json.loads(tempdocs.replace("'",'"'), strict=False)
        temptimes = 0
        for docitem in docs:
            if whetherrepeatset:
                temptimes += 1
                if temptimes > repeattimes:
                    break
            # print(docitem)
            # docitem = json.loads(docitem)
            # print(type(docitem["snippet"]))
            alldata[filename]["text"] += filename + '\n' + docitem["snippet"] + '\n\n'
            alldata[filename]["index"].append(docitem["title"])
            # print(alldata)

    return alldata

    
count = 0
whetherrag = False
alldata = jsonloaddoc("/home/jingwangyuan/work/doc.json",True,10)
for fileindex in range(len(filename1)):
    print(filename1[fileindex],first_column[fileindex])
    txtname = filename1[fileindex].replace('.pdf','.txt')
    
    # split chunk
    texts = chunksplit(txtname,txtlo)
    
    # control the length of chunk
    chunkstrict = chunklenstrict(texts)
    
    question = first_column[fileindex] 

    # cohere rag
    if whetherrag:
        ans_source,ans_01 = cohererag(chunkstrict,texts,co,question,ans_01,ans_source,coheredocall,cohereciaall)
        sourcecollection.append(ans_source) 

        # message information generation
        allmessage,wronginformation,templenchunk = messagegeneration(ans_source,texts,wronginformation,False,5,90000,filename1[fileindex])
    
        sourcelencollection.append(templenchunk)
        finalmessage = startmessage + allmessage + endmessage + question
        
    else:

        allcontext = alldata[filename1[fileindex]]["text"]
        if len(allcontext)>90000:
            count += 1
            allcontext = allcontext[:90000]
        finalmessage = startmessage + allcontext + endmessage + question
    # print(finalmessage) 
    print('+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++')
    
    allanswer = cohereanswer(co,finalmessage,ans_01,ans_source,allanswer)

# print(count)
print("所有问题最终结果",allanswer)            
print("错误",wronginformation)
print("源：",sourcecollection)
print("长度分布",sourcelencollection)

# 保存rag中间结果
coheredocstore = json.dumps(coheredocall,ensure_ascii = False)
cohereciastore = json.dumps(cohereciaall,ensure_ascii = False)
if whetherrag:
    with open('doc.json',"w") as fpp:
        fpp.write(coheredocstore )
    with open('cia.json',"w") as fppp:
        fppp.write(cohereciastore)

import pandas as pd
df = pd.DataFrame({"rag_answer":allanswer})
df.to_excel("dan2.xlsx",index = False)

