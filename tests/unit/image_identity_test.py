import hashlib
import json
import unittest
from src.control.image_identity import checked_identity
from src.control.store import comparison_issues

class ImageIdentityTests(unittest.TestCase):
    def test_index_and_executable_membership_require_matching_raw_hashes(self):
        raw=json.dumps({'config':{'digest':'sha256:config'},'layers':[{'digest':'sha256:layer'}]}).encode()
        digest='sha256:'+hashlib.sha256(raw).hexdigest()
        index=json.dumps({'manifests':[{'digest':digest,'mediaType':'application/vnd.oci.image.manifest.v1+json','platform':{'os':'linux','architecture':'arm64'}}]}).encode()
        image='sha256:'+hashlib.sha256(index).hexdigest()
        self.assertEqual(checked_identity(image,index,raw)['executionDigest'],digest)
        self.assertRaises(ValueError,checked_identity,image,index+b' ',raw)
        self.assertRaises(ValueError,checked_identity,image,index,raw+b' ')
    def test_only_verified_execution_equality_removes_build_metadata_difference(self):
        context={'taskSourcesDigest':'task','taskImageIds':['main','qsim'],'verifierImageId':'verifier','runnerImageId':'index-one'}
        a={'task':'task','comparisonContext':dict(context)}
        b={'task':'task','comparisonContext':{**context,'runnerImageId':'index-two'}}
        self.assertTrue(comparison_issues([a,b]))
        a['comparisonContext']['runnerExecutionManifest']='same-runtime'
        self.assertTrue(comparison_issues([a,b]))
        b['comparisonContext']['runnerExecutionManifest']='same-runtime'
        self.assertEqual(comparison_issues([a,b]),[])
        b['comparisonContext']['taskImageIds']=['different-main','qsim']
        self.assertTrue(comparison_issues([a,b]))
