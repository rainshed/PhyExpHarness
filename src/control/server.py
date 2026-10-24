"""Local authenticated API. UI and Meta are clients; supervision belongs to this process and its children."""
import argparse
import asyncio
import contextlib
import fcntl
import json
import sqlite3
from pathlib import Path
from .stop_policy import CONTROLLED_POLICIES
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import JSONResponse,FileResponse,Response
from .service import ControlService
from .store import Refused,Conflict
from .database import busy as database_busy
from .paths import data_dir
from src.execution.host.models import load_model_config
from .inspection import plugin_source,open_folder,export_folder,export_guide


def make_app(service,supervise=True):
    @contextlib.asynccontextmanager
    async def lifespan(app):
        async def loop():
            while True:
                try:await asyncio.to_thread(service.tick)
                except Exception as error:
                    (service.data/'supervisor-errors.jsonl').open('a').write(json.dumps({'error':str(error)})+'\n')
                await asyncio.sleep(.5)
        task=asyncio.create_task(loop()) if supervise else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):await task
        # Do not terminate running Trial supervisors on a UI/API disconnect or service restart.
    app=FastAPI(title='PhyExpHarness control',version='1',lifespan=lifespan)
    @app.exception_handler(Refused)
    async def refused(_request,error):return JSONResponse({'error':str(error)},status_code=403)
    @app.exception_handler(Conflict)
    async def conflict(_request,error):return JSONResponse({'error':str(error)},status_code=409)
    @app.exception_handler(KeyError)
    async def missing(_request,error):return JSONResponse({'error':'Object unavailable'},status_code=404)
    @app.exception_handler(ValueError)
    async def invalid(_request,error):return JSONResponse({'error':str(error)},status_code=400)
    @app.exception_handler(TypeError)
    async def invalid_type(_request,error):return JSONResponse({'error':'Invalid operation arguments: '+str(error)},status_code=400)
    def database_error(error,request):
        busy=database_busy(error)
        legacy=request.url.path.startswith('/accounting/')
        return JSONResponse({'error':'控制数据库暂时繁忙；请稍后用原请求核对结果。' if busy else '控制数据库异常',
            'code':('accounting_unavailable' if legacy else 'control_database_busy') if busy else 'control_database_error',
            'source':'control-database',**({'retryAfterMs':500} if busy else {})},
            status_code=503 if busy else 500,headers={'Cache-Control':'no-store'})
    @app.exception_handler(sqlite3.OperationalError)
    async def database_unavailable(request,error):return database_error(error,request)
    @app.middleware('http')
    async def boundary(request,call_next):
        try:length=int(request.headers.get('content-length','0'))
        except ValueError:return JSONResponse({'error':'Invalid content length'},status_code=400)
        if length>4_000_000:return JSONResponse({'error':'Request too large'},status_code=413)
        try:request.state.identity=await asyncio.to_thread(service.authenticate,request.headers.get('authorization','').removeprefix('Bearer '))
        except Refused as error:
            modern=request.url.path.startswith('/model-access/')
            code=('request_lease_expired' if modern else 'accounting_lease_expired') if 'expired' in str(error).lower() else ('request_auth_failed' if modern else 'accounting_auth_failed')
            return JSONResponse({'error':str(error),'code':code},status_code=401)
        except sqlite3.OperationalError as error:return database_error(error,request)
        try:
            service.deletions.guard_route(request.url.path)
            response=await call_next(request)
        except Conflict as error:
            response=JSONResponse({'error':str(error)},status_code=409)
        response.headers['Cache-Control']='no-store';return response
    class ActivityRequests:
        def __init__(self,app):self.app=app
        async def __call__(self,scope,receive,send):
            if scope['type']!='http':return await self.app(scope,receive,send)
            # ASGI scope includes the entire download body. call_next() alone
            # returns at headers and would release a file before it is streamed.
            try:
                with service.access.enter():await self.app(scope,receive,send)
            except Conflict as error:
                await JSONResponse({'error':str(error)},status_code=409,headers={'Cache-Control':'no-store'})(scope,receive,send)
    app.add_middleware(ActivityRequests)
    def user(request):
        if request.state.identity['role']!='user':raise Refused('User authority required')
    @app.get('/health')
    def health(request:Request):
        user(request);return {'schemaVersion':1,'status':'running','service':'independent-control','campaigns':len(service.store.list('campaigns'))}
    @app.post('/reference-native-sync')
    def reference_sync(request:Request,body:dict):
        user(request);return service.references.catalog.sync(body)
    @app.get('/references/catalog')
    def reference_catalog(request:Request):
        user(request);return service.references.catalog.public()
    @app.get('/campaigns/{id}/references')
    def reference_status(id:str,request:Request,offset:int=0,limit:int=50):
        user(request);return service.references.status(id,{'offset':offset,'limit':limit})
    @app.post('/campaigns/{id}/references')
    def reference_policy(id:str,request:Request,body:dict):
        user(request);return service.references.update(id,body['policy'],body['idempotencyKey'],body['expectedRevision'],body.get('stopRunning',False))
    @app.post('/campaigns/{id}/references/cancel')
    def reference_cancel(id:str,request:Request,body:dict):
        user(request);return service.references.cancel(id,body)
    @app.get('/storage')
    def storage(request:Request):
        user(request);return service.storage.snapshot()
    @app.put('/storage/policy')
    @app.post('/storage/policy')
    def storage_policy(request:Request,body:dict):
        user(request);return service.storage.configure(body)
    @app.get('/models')
    def models(request:Request):
        user(request);return service.providers.catalog()
    @app.get('/tasks')
    def tasks(request:Request):
        user(request);return service.task_catalog()
    @app.get('/providers')
    def providers(request:Request):
        user(request);return service.providers.snapshot()
    @app.post('/providers/save')
    def save_provider(request:Request,body:dict):
        user(request);return service.providers.save(body)
    @app.post('/providers/{id}/credential/remove')
    def remove_provider_credential(id:str,request:Request,body:dict):
        user(request);return service.providers.remove_credential(id,body)
    @app.post('/providers/{id}/test')
    def test_provider(id:str,request:Request,body:dict):
        user(request);return service.providers.start_test(id,body)
    @app.get('/provider-tests/{id}')
    def provider_test(id:str,request:Request):
        user(request);return service.providers.get_test(id)
    @app.get('/campaigns')
    def campaigns(request:Request):
        user(request);return service.list_status()
    @app.post('/campaigns')
    def create(request:Request,body:dict):
        user(request);return service.create(body['config'],body['idempotencyKey'],body.get('modelCatalogRevision'),source='user_submitted')
    @app.get('/campaigns/{id}')
    def campaign(id:str,request:Request):
        user(request);return service.status(id)
    @app.get('/campaigns/{id}/deletion')
    def deletion(id:str,request:Request):
        user(request);return service.deletions.preview(id)
    @app.post('/campaigns/{id}/deletion')
    def delete_campaign(id:str,request:Request,body:dict):
        user(request);return service.deletions.request(id,body.get('expectedRevision'),body.get('idempotencyKey'),body.get('retry',False))
    @app.get('/campaigns/{id}/selections/{decision}')
    def selection(id:str,decision:str,request:Request):
        user(request);row=service.store.get('selection_decisions',decision)
        if row['campaignId']!=id:raise Refused('Decision outside Campaign')
        return row
    @app.get('/campaigns/{id}/sources')
    def sources(id:str,request:Request):
        user(request);return service.adoptions.list(id)
    @app.get('/campaigns/{id}/sources/{source}')
    def source_read(id:str,source:str,request:Request,offset:int=0):
        user(request);return service.adoptions.read(id,source,offset)
    @app.post('/campaigns/{id}/sources')
    def adopt_source(id:str,request:Request,body:dict):
        user(request);return service.adoptions.adopt(id,**body)
    @app.get('/campaigns/{id}/research')
    def research(id:str,request:Request,offset:int=0,limit:int=20,pluginKey:str|None=None,relation:str|None=None):
        user(request);return service.research.overview(id,offset,limit,pluginKey,relation)
    @app.get('/campaigns/{id}/research/{record}')
    def research_detail(id:str,record:str,request:Request,revision:int):
        user(request);return service.research.detail(id,record,revision)
    @app.post('/campaigns/{id}/research')
    def research_save(id:str,request:Request,body:dict):
        user(request);return service.research.save(id,**body,author='user')
    @app.post('/campaigns/{id}/excerpt')
    def excerpt(id:str,request:Request,body:dict):
        user(request);return service.evidence.excerpt(id,body)
    @app.get('/campaigns/{id}/events')
    def events(id:str,request:Request,after:int=0):
        user(request)
        if service.store.deletion(id):return []
        return service.store.events(id,after)
    @app.post('/campaigns/{id}/control')
    def control(id:str,request:Request,body:dict):
        user(request);return service.control(id,body['action'],body['idempotencyKey'],body.get('expectedRevision'),body.get('changes'))
    @app.post('/campaigns/{id}/plan')
    def plan(id:str,request:Request,body:dict):
        user(request);return service.store.update_plan(id,body['changes'],body['reason'],body['idempotencyKey'],body['expectedPlanRevision'],source='user')
    @app.post('/trials/{id}/stop')
    def stop_trial(id:str,request:Request):
        user(request);trial=service.store.run(id)
        if trial['state'] in ['launching','running']:service.stop_trial(trial,'user_stop')
        return service.store.run(id)
    @app.post('/trials/{id}/recollect')
    def recollect(id:str,request:Request):
        user(request);return service.recollect(id)
    @app.get('/evidence/{id}')
    def evidence(id:str,request:Request,offset:int=0,limit:int=16000):
        user(request);row=service.store.get('evidence',id);return service.evidence.read(row['campaignId'],id,offset,limit)
    @app.get('/reports/{id}')
    def report(id:str,request:Request):
        user(request);return service.reports.view(service.store.get('reports',id))
    @app.get('/reports/{id}/download')
    def report_download(id:str,request:Request):
        user(request);row=service.reports.view(service.store.get('reports',id))
        from urllib.parse import quote
        filename=('进化总报告' if not row['batchId'] else '第'+str(service.store.get('batches',row['batchId'])['round'])+'轮报告')+'.md'
        return Response(row['markdown'],media_type='text/markdown',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename)})
    @app.get('/candidates/{id}/plugins/{plugin}')
    def source(id:str,plugin:str,request:Request,file:str|None=None):
        user(request);return plugin_source(service,id,plugin,file)
    @app.post('/candidates/{id}/plugins/{plugin}/open')
    def source_open(id:str,plugin:str,request:Request):
        user(request);return open_folder(plugin_source(service,id,plugin)['directory'])
    @app.post('/candidates/{id}/name')
    def rename(id:str,request:Request,body:dict):
        user(request);name=body.get('name')
        if not isinstance(name,str) or not name.strip() or len(name)>80 or any(ord(x)<32 for x in name):raise Refused('请输入 1–80 字的版本名称')
        row=service.store.get('candidates',id);row['displayName']=name.strip();service.store.put('candidates',row)
        if service.store.get('campaigns',row['campaignId'])['state'] in ['finished','failed']:
            latest={}
            for r in service.store.list('reports',row['campaignId']):latest[(r['kind'],r['batchId'])]=r
            for r in latest.values():service.reports.refresh_presentation(r['id'])
        return {'renamed':True}
    @app.post('/exports/{id}/open')
    def exported_open(id:str,request:Request):
        user(request);return open_folder(export_folder(service,id))
    @app.get('/exports/{id}/guide')
    def guide(id:str,request:Request):
        user(request);return export_guide(service,id)
    @app.get('/exports/{id}/guide/download')
    def guide_download(id:str,request:Request):
        user(request);g=export_guide(service,id)
        from urllib.parse import quote
        return Response(g['markdown'],media_type='text/markdown',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(g['filename'])})
    @app.post('/exports')
    def export(request:Request,body:dict):
        user(request);return service.export(body['campaignId'],body['candidateId'])
    @app.post('/exports/{id}/validate')
    def export_validate(id:str,request:Request):
        user(request);return service.validate_export(id)
    @app.get('/exports/{id}/download')
    def export_download(id:str,request:Request):
        user(request);row=service.store.get('exports',id);return FileResponse(row['archive'],filename=export_guide(service,id)['title']+'.zip',media_type='application/zip')
    @app.post('/meta/{campaign}')
    def meta(campaign:str,request:Request,body:dict):
        role=request.state.identity
        if role['role']!='meta' or role['campaignId']!=campaign:raise Refused('Meta lease required for this Campaign')
        if service.store.get('campaigns',campaign)['config'].get('stopPolicy') in CONTROLLED_POLICIES:raise Refused('Composed Meta must use authenticated runtime channel')
        return service.meta_call(campaign,body['operation'],body.get('input',{}))
    @app.post('/meta-sessions/{id}/runtime')
    def runtime(id:str,request:Request,body:dict):
        row=service.store.get('meta_sessions',id);role=request.state.identity
        if role.get('id')!=row['leaseId'] or role['role']!='meta':raise Refused('Meta session lease mismatch')
        if body['action']=='user_question':
            from .meta_questions import request as question_request
            args=body.get('input',{})
            return question_request(service.store,id,args.get('agentId'),args.get('callId'),args.get('questions'))
        try:return service.stop_runtime.dispatch(id,body['action'],body.get('input',{}))
        except (Refused,Conflict,KeyError,ValueError,TypeError) as error:
            if row.get('runtimeVersion')!='meta-runtime-v2' or body['action']!='call':raise
            code='conflict' if isinstance(error,Conflict) else 'unavailable' if isinstance(error,KeyError) else 'refused' if isinstance(error,Refused) else 'invalid_input'
            return {'ok':False,'error':{'code':code,'message':str(error),'retryable':False}}
    @app.post('/meta-questions/{id}/answer')
    def question_answer(id:str,request:Request,body:dict):
        user(request)
        from .meta_questions import answer
        return answer(service.store,id,body)
    @app.get('/meta-sessions/{id}/notifications')
    def notifications(id:str,request:Request,after:int=0):
        row=service.store.get('meta_sessions',id);role=request.state.identity
        if role.get('id')!=row['leaseId'] or role['role']!='meta':raise Refused('Meta session lease mismatch')
        if not service.meta_driver:raise Refused('Meta driver unavailable')
        return service.meta_driver.notifications(id,after)
    @app.post('/meta-sessions/{id}/ack')
    def acknowledge(id:str,request:Request,body:dict):
        row=service.store.get('meta_sessions',id);role=request.state.identity
        if role.get('id')!=row['leaseId'] or role['role']!='meta':raise Refused('Meta session lease mismatch')
        if not service.meta_driver:raise Refused('Meta driver unavailable')
        return service.meta_driver.acknowledge(id,body.get('cursor'))
    @app.post('/model-access/{lease_id}')
    def model_access(lease_id:str,request:Request,body:dict):
        from .model_access import check_access
        lease=request.state.identity
        if lease.get('id')!=lease_id or lease['role'] not in ('meta','solver'):raise Refused('Model access lease mismatch')
        decision=check_access(service.store,lease_id,body.get('agentId'))
        if decision['status']=='granted' and not service.storage.permit(lease['campaignId'],'request'):
            decision={'status':'waiting','code':'storage_capacity_wait'}
        return JSONResponse(decision,status_code=200 if decision['status']=='granted' else 429 if decision['status']=='waiting' else 403)
    # Compatibility endpoint for pre-existing frozen runtimes only.
    @app.post('/accounting/{lease_id}/{action}')
    def accounting(lease_id:str,action:str,request:Request,body:dict):
        lease=request.state.identity
        if lease.get('id')!=lease_id or lease['role'] not in ['meta','solver']:raise Refused('Accounting lease mismatch')
        campaign=lease['campaignId']
        if action=='reserve':
            if not service.storage.permit(campaign,'request'):
                return JSONResponse({'status':'waiting','code':'storage_capacity_wait','retryAfterMs':1000,'boundary':'host_storage'},status_code=429)
            if body.get('admissionVersion')==1:
                decision=service.store.admit(campaign,lease_id,body['id'],body['reservedTokens'],lease['role'])
                return JSONResponse(decision,status_code=200 if decision['status']=='granted' else 429 if decision['status']=='waiting' else 403)
            return service.store.reserve(campaign,lease_id,body['id'],body['reservedTokens'],lease['role'])
        if action=='settle':return service.store.settle(campaign,lease_id,body['id'],body.get('confirmedTokens'),body.get('unknown',True))
        raise Refused('Accounting action unavailable')
    return app

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--model-config',type=Path,help='Provider/model JSON file; otherwise PHYEXP_MODEL_CONFIG or built-in defaults')
    parser.add_argument('--quantum-harbor',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18402)
    args=parser.parse_args();data=data_dir(args.data_dir);data.mkdir(parents=True,exist_ok=True)
    lock=(data/'control.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('A control service already owns this data directory')
    if args.model_config:
        import os
        os.environ['PHYEXP_MODEL_CONFIG']=str(args.model_config.expanduser().resolve())
    load_model_config()  # Fail before starting supervision when deployment configuration is invalid.
    service=ControlService(Path(__file__).resolve().parents[2],data,args.quantum_harbor,f'http://127.0.0.1:{args.port}')
    from .meta import MetaDriver
    service.meta_driver=MetaDriver(service)
    import uvicorn
    uvicorn.run(make_app(service),host='127.0.0.1',port=args.port,log_level='warning')
if __name__=='__main__':main()
