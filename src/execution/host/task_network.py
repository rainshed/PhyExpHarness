"""Move only this Trial's main container onto an internal network with its qsim sidecar."""
import json,subprocess,uuid

def docker(*args):
    return subprocess.check_output(['docker',*args],text=True).strip()

def restrict_main(main,qsim,owner=None):
    network='phyexp-trial-'+str(uuid.uuid4())
    labels=['--label','phyexp.managed=trial']
    if owner:labels+=['--label','phyexp.launch='+owner]
    docker('network','create','--internal',*labels,network)
    try:
        docker('network','connect','--alias','qsim',network,qsim)
        docker('network','connect',network,main)
        config=json.loads(docker('inspect',main))[0]
        for name in config['NetworkSettings']['Networks']:
            if name!=network:docker('network','disconnect',name,main)
        networks=json.loads(docker('inspect',main))[0]['NetworkSettings']['Networks']
        if list(networks)!=[network]:raise RuntimeError('Main retains an unapproved network')
        return network
    except BaseException:
        release(network,main,qsim)
        raise

def release(network,main,qsim):
    for container in [main,qsim]:subprocess.run(['docker','network','disconnect','-f',network,container],capture_output=True)
    subprocess.run(['docker','network','rm',network],capture_output=True)
