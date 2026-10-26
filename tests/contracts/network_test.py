"""Real Docker boundary test, fake HTTP sidecar, no model or science task."""
import unittest,subprocess,uuid,json,os
from src.execution.host.task_network import restrict_main,release,docker
class Network(unittest.TestCase):
 def test_main_reaches_qsim_but_not_public_network_or_host(self):
  prefix='phyexp-net-'+uuid.uuid4().hex[:10];main=prefix+'-main';qsim=prefix+'-qsim';network=None
  try:
   docker('run','-d','--name',qsim,'--entrypoint','node','phyexp-runner:0.2.1-rc.2','-e',"require('http').createServer((q,s)=>s.end('qsim-fixture')).listen(8123,'0.0.0.0')")
   docker('run','-d','--name',main,'--entrypoint','sleep',os.environ.get('PHYEXP_TASK_TEST_IMAGE','qiqcbench-agent:latest'),'60')
   network=restrict_main(main,qsim)
   script="""import urllib.request,json,socket
out={}
for name,url in [('qsim','http://qsim:8123'),('internet','http://1.1.1.1'),('host','http://host.docker.internal:18402')]:
 try:
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
  out[name]=opener.open(url,timeout=2).read().decode()
 except Exception:out[name]=None
print(json.dumps(out))
"""
   result=json.loads(docker('exec',main,'python3','-c',script))
   self.assertEqual(result,{'qsim':'qsim-fixture','internet':None,'host':None})
  finally:
   if network:release(network,main,qsim)
   for container in [main,qsim]:subprocess.run(['docker','rm','-f',container],capture_output=True)
if __name__=='__main__':unittest.main()
