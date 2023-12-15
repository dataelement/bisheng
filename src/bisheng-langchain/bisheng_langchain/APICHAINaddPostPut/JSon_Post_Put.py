"""
2023/12/8,说明：
APIdocs是指引大模型进行API调用的文档。
对于GET方法，应该包含的内容有："API URL"：要访问的URL地址；URL_example：one-shot提示，一个URL的例子；所有key的说明，
以及tool_name：这个工具是干嘛的,还有"HTTP METHOD"。
对于POST等方法，应当包含"API URL"，JSON——example，以及参数说明（是否必须，参数含义等）。以及tool_name：这个工具是干嘛的。"HTTP METHOD"
以上内容写的时候尽量清晰，这样大模型判读才不会有误，自动化成功率会很高。
大模型会根据question以及apidocs生成合适的内容进行api请求
"""

# 实在智能创建任务
tool1 = {
    "HTTP METHOD": "POST",
    "API URL": "https://z-commander-api.ai-indeed.com/openAPI/v1/job",
    'JSON_example': '''
{ "jobName":"测试任务",//任务名称
"processDetailUUID":"e8a2f88a2a470c2b5f9b9140e1d2225a",//创建/获取到的流程版本的UUID
"executeTimes":1,//执行的次数。不能超过 30 次。
"executeType":2,//执行方式, 2-立即执行 9-定时执行
"cronExpression":"* * * * * ?",//时间表达式，执行方式选择为定时执行时必填，内容为Cron 表达式
"inputParam":{ //机器人任务入参，json 格式，任务执行时使用。 "param1":"value1", "param2":"value2"},
"priority": 1, // 任务优先级 1-高，2-中，3-低
"distributionType": 2, // 分配类型：1-自动分配，2-指定 bot 机器人；分配类型为 2（指定 bot 机器人）时，botList 属性不能为空
"botList": [ { "botUUID": "fVbcpvj1jG0Qoak5nI1CUUBBYabCb5mX", // 机器人 botUUID
             "priority": 1 // 优先级 1-高，2-中，3-低 },
{ "botUUID": "pYRA8fvWWgRmhZcGj4GNuZNj5lWi7c9n", // 机器人 botUUID
"priority": 1 // 优先级 1-高，2-中，3-低 }]}''',

    'api_docs': '''jobName String 是 任务的名称(最长三十个字符)processDetailUUID String 是 创建/获取到的流程版本 UUIDexecuteTimes Integer 否 
执行的次数。不能超过 30 次。executeType Integer 是 执行方式, 2-立即执行 9-定时执行cronExpression String 否时间表达式，执行方式选择为定时执行时必填，内容为 Cron 
表达式inputParam Object 否 机器人任务入参，json 格式，任务执行时使用。priority Integer 否 任务优先级 1-高，2-中，3-低，默认 2-中distributionType Integer 否分配类型：1-自动分配，2-指定 bot 机器人；分配类型为 2（指定 bot 机器人）时，botList 属性不能为空，默认 1-自动分配botList List 否bot 机器人列表，当分配类型为 2-指定 bot 机器人时，需要传递此参数''',
    'tool_name': "任务创建"
}
#任务处理
tool2 = {
    "接口说明": "该接口是为了对已经创建的任务进行操作所提供的接口 操作类型:1-立即/再次执行任务 2-停止任务 3-强制停止任务(bot 触发的手动触发类型的任务) 4-删除任务",
    "URL": "https://z-commander-api.ai-indeed.com/openAPI/v1/job/{jobUUID}/{operation}",
    "HTTP method": "PUT",
    "Content-Type": "application/json",
    'JSON_example': '''http://commander-manager.dev.ii-ai.tech/openAPI/v1/job/ea5adaads4123/. Body 请求样例{
    "inputParam":{ //机器人任务入参，json 格式，任务执行时使用。 "param1":"value1", "param2":"value2"}}''',
    'api_docs': '''Body参数说明:inputParam Object 任务入参，仅在任务立即执行/再次执行时，如果传递该参数，那么会先更新任务入参，再执行任务''',
    "响应样例": '''{ 'msg': "success",  "code": 0,// 0 为成功 "data": true}''',
    'tool_name': "任务处理"
}
#宠物查询
tool3 = {'''
    HTTP METHOD = GET
    tool_name = "pet query"
    URL_example = "https://api.jisuapi.com/pet/query?appkey=<YOUR_API_KEY>&name=拉布拉多"
    key说明 = "name关键字代表宠物名字；appkey代表密钥，一个可用的密钥是4b13addb8994d645。"
    '''
         }
