"""Bounded business completion after authoritative native Skill/tool evidence.

Only an authenticated native task containing this run's unguessable capability
may be bound. Cookies live in one worker's memory and are never persisted.
"""
import json
import threading
import time
import urllib.parse
import urllib.request

from native_bridge import NativeBridgeError
from workflow import WorkflowError


class CompletionSupervisor:
    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()
        self.jobs = {}

    def bind(self, runid, token, cookie, task):
        self.app.workflow.get(runid, token)
        chat, version = task.get('chat_id'), task.get('session_version_id')
        from native_bridge import IDENTIFIER
        if any(not isinstance(x, str) or not IDENTIFIER.fullmatch(x) for x in (chat, version)):
            raise WorkflowError('原生任务标识无效', 400)
        if not cookie or len(cookie)>16384 or any(ord(c)<32 or ord(c)==127 for c in cookie):
            raise WorkflowError('平台登录已失效，请重新登录', 401)
        with self.lock:
            old=self.jobs.get(runid)
            if old:
                if old['task'] != {'chat_id':chat,'session_version_id':version}:
                    raise WorkflowError('本次运行已绑定其他原生任务',409)
                return {'ok':True,'state':'bound','run_id':runid}
        versions,_=self.app.native._get('/workspace/api/v1/linsight/workbench/session-version-list?'+urllib.parse.urlencode({'session_id':chat}),cookie)
        v=next((v for v in versions if v.get('id')==version),None) if isinstance(versions,list) else None
        # Exact capability in a task created by this run. Never terminate an
        # arbitrary task selected by a client, even if it can be read.
        if not v or v.get('session_id')!=chat or not isinstance(v.get('question'),str) or runid not in v['question'] or token not in v['question'] or 'procurement-forecast-fast' not in (v.get('skills') or []):
            raise WorkflowError('原生任务不属于本次预测运行',409)
        job={'task':{'chat_id':chat,'session_version_id':version},'state':'running'}
        with self.lock:
            if runid in self.jobs:raise WorkflowError('任务绑定冲突，请读取原运行状态',409)
            self.jobs[runid]=job
        threading.Thread(target=self._complete,args=(runid,token,cookie,job),daemon=True).start()
        return {'ok':True,'state':'bound','run_id':runid}

    def _stop(self,cookie,task):
        request=urllib.request.Request(self.app.native.base_url+'/workspace/api/v1/linsight/workbench/terminate-execute',
            data=json.dumps({'linsight_session_version_id':task['session_version_id']}).encode(),
            headers={'Cookie':cookie,'Content-Type':'application/json'},method='POST')
        try:
            with self.app.native.opener.open(request,timeout=2) as response:
                data=json.loads(response.read(65536))
            return data.get('status_code',200)==200
        except Exception:return False

    def _complete(self,runid,token,cookie,job):
        # The frontend imposes the same absolute 30s click budget. This worker
        # survives a closed tab, and never runs an unbounded model retry loop.
        try:
            deadline=time.monotonic()+max(0,28-self.app.workflow.get(runid,token).get('elapsed_seconds',0))
            while time.monotonic()<deadline:
                state=self.app.workflow.get(runid,token)
                if state['state'] in ('stage_failed','timed_out'):
                    job['state']='failed';break
                if state['state']=='completed':
                    job['state']='completed';break
                if state['state']=='awaiting_native_verification':
                    contract=self.app.workflow.verification_contract(runid,token)
                    try:
                        evidence=self.app.native.verify(cookie,job['task']['chat_id'],job['task']['session_version_id'],
                            {'run_id':runid,'native_tool_key':self.app.native_tool_key,**contract},business_checkpoint=True)
                    except NativeBridgeError as exc:
                        # Tool end records can lag the API response briefly.
                        # No evidence means no report; never trust client output.
                        if exc.status!=409:raise
                    else:
                        if time.monotonic()>=deadline:
                            self.app.workflow.expire(runid,token,'分析超过30秒预算，任务已停止；本次未生成已核验报告。')
                            job['state']='timed_out';break
                        self.app.workflow.verify(runid,token,evidence,deadline=deadline)
                        job['state']='completed';break
                time.sleep(.25)
            else:
                job['state']='timed_out'
                if hasattr(self.app.workflow,'expire'):
                    self.app.workflow.expire(runid,token,'分析超过30秒预算，任务已停止；本次未生成已核验报告。')
        except (NativeBridgeError,WorkflowError) as exc:
            job['state']='failed'
            job['error']=str(exc)
            try:self.app.workflow.expire(runid,token,'执行核验未完成：'+str(exc))
            except WorkflowError:pass
        finally:
            job['native_stop_confirmed']=self._stop(cookie,job['task'])
            # cookie and token leave scope; neither is stored in self.jobs.
