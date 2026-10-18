"""Local authenticated API. UI and Meta are clients; supervision belongs to this process and its children."""
import argparse
import asyncio
import contextlib
import fcntl
import json
from pathlib import Path
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import JSONResponse,FileResponse,Response
from .service import ControlService
from .store import Refused,Conflict
from .paths import data_dir
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
    @app.middleware('http')
    async def boundary(request,call_next):
        try:length=int(request.headers.get('content-length','0'))
        except ValueError:return JSONResponse({'error':'Invalid content length'},status_code=400)
        if length>4_000_000:return JSONResponse({'error':'Request too large'},status_code=413)
        try:request.state.identity=service.authenticate(request.headers.get('authorization','').removeprefix('Bearer '))
        except Refused as error:return JSONResponse({'error':str(error)},status_code=401)
        response=await call_next(request);response.headers['Cache-Control']='no-store';return response
    def user(request):
        if request.state.identity['role']!='user':raise Refused('User authority required')
    @app.get('/health')
    def health(request:Request):
        user(request);return {'schemaVersion':1,'status':'running','service':'independent-control','campaigns':len(service.store.list('campaigns'))}
    @app.get('/models')
    def models(request:Request):
        user(request);return {'models':['gpt-6-sol','gpt-6-astra','gpt-6-luna'],'provider':'openai-codex','limitKind':'soft','hardOutputLimitVerified':False}
    @app.get('/campaigns')
    def campaigns(request:Request):
        user(request);return [service.store.status(c['id']) for c in service.store.list('campaigns')]
    @app.post('/campaigns')
    def create(request:Request,body:dict):
        user(request);return service.create(body['config'],body['idempotencyKey'])
    @app.get('/campaigns/{id}')
    def campaign(id:str,request:Request):
        user(request);return service.status(id)
    @app.get('/campaigns/{id}/events')
    def events(id:str,request:Request,after:int=0):
        user(request);return service.store.events(id,after)
    @app.post('/campaigns/{id}/control')
    def control(id:str,request:Request,body:dict):
        user(request);return service.control(id,body['action'],body['idempotencyKey'],body.get('expectedRevision'),body.get('changes'))
    @app.get('/evidence/{id}')
    def evidence(id:str,request:Request,offset:int=0,limit:int=16000):
        user(request);row=service.store.get('evidence',id);return service.evidence.read(row['campaignId'],id,offset,limit)
    @app.get('/reports/{id}')
    def report(id:str,request:Request):
        user(request);row=service.store.get('reports',id);return {**row,'markdown':Path(row['markdownPath']).read_text()}
    @app.get('/reports/{id}/download')
    def report_download(id:str,request:Request):
        user(request);row=service.store.get('reports',id);return FileResponse(row['markdownPath'],filename=('进化总报告' if not row['batchId'] else '第'+str(service.store.get('batches',row['batchId'])['round'])+'轮报告')+'.md',media_type='text/markdown')
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
        return service.meta_call(campaign,body['operation'],body.get('input',{}))
    @app.get('/meta-sessions/{id}/notifications')
    def notifications(id:str,request:Request,after:int=0):
        row=service.store.get('meta_sessions',id);role=request.state.identity
        if role.get('id')!=row['leaseId'] or role['role']!='meta':raise Refused('Meta session lease mismatch')
        if not service.meta_driver:raise Refused('Meta driver unavailable')
        return service.meta_driver.notifications(id,after)
    @app.post('/accounting/{lease_id}/{action}')
    def accounting(lease_id:str,action:str,request:Request,body:dict):
        lease=request.state.identity
        if lease.get('id')!=lease_id or lease['role'] not in ['meta','solver']:raise Refused('Accounting lease mismatch')
        campaign=lease['campaignId']
        if action=='reserve':return service.store.reserve(campaign,lease_id,body['id'],body['reservedTokens'],lease['role'])
        if action=='settle':return service.store.settle(campaign,lease_id,body['id'],body.get('confirmedTokens'),body.get('unknown',True))
        raise Refused('Accounting action unavailable')
    return app

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--quantum-harbor',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18402)
    args=parser.parse_args();data=data_dir(args.data_dir);data.mkdir(parents=True,exist_ok=True)
    lock=(data/'control.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('A control service already owns this data directory')
    service=ControlService(Path(__file__).resolve().parents[2],data,args.quantum_harbor,f'http://127.0.0.1:{args.port}')
    from .meta import MetaDriver
    service.meta_driver=MetaDriver(service)
    import uvicorn
    uvicorn.run(make_app(service),host='127.0.0.1',port=args.port,log_level='warning')
if __name__=='__main__':main()
