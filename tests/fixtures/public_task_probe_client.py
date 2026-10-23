"""Deterministic container compatibility probes, not a scientific solver.

Runs inside main through the same public MCP interface as Solver. Deliberately
weak submissions exercise evidence and official scoring without model calls.
Never imports qsim implementation or reads private scoring inputs.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import socket
import sys
import time
import urllib.request

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

DEVICES = {
    'time_budgeted_hamlearn_10q': 'hamlearn_10q_chain_v1',
    'time_budgeted_shadow_surrogate_60q': 'boundedgate_60q_v0',
    'tunable_coupler_cz_netzero': 'tunable_coupler_cz_v0',
    'logical_cnot_decoder_calibration': 'sc_lattice_surgery_114q_v0',
    'adaptive_clustered_clbcs_h2o': 'clbcs_h2o_14q_v0',
}
NOTE = 'Deterministic deployment fixture; no fitted scientific solution or model calls.'


def isolation():
    for path in ['/verifier/private', '/app/configs', '/app/qiqcbench_configs',
                 '/var/run/docker.sock', '/qsim_logs/experiment_log.jsonl']:
        assert not Path(path).exists(), 'Private path exposed: '+path
    status = Path('/proc/self/status').read_text()
    assert 'CapEff:\t0000000000000000' in status
    assert 'NoNewPrivs:\t1' in status and 'Seccomp:\t2' in status
    for url in ['http://1.1.1.1', 'http://host.containers.internal:18412']:
        try:
            urllib.request.urlopen(url, timeout=2)
        except Exception:
            pass
        else:
            raise AssertionError('Main reached forbidden address: '+url)
    try:
        socket.getaddrinfo('example.com', 80)
    except OSError:
        pass
    else:
        raise AssertionError('Main retains external DNS')
    delivery = Path('/qsim_logs/public_job_results')
    try:
        (delivery/'must-not-write').write_text('probe')
    except OSError:
        pass
    else:
        raise AssertionError('Public result delivery is writable')
    return {'privatePathsAbsent': True, 'capabilitiesDropped': True, 'noNewPrivileges': True,
            'seccompEnabled': True, 'externalNetworkBlocked': True, 'publicEvidenceReadOnly': True,
            'cpuMax': Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
            'memoryMax': Path('/sys/fs/cgroup/memory.max').read_text().strip(),
            'pidsMax': Path('/sys/fs/cgroup/pids.max').read_text().strip()}


async def exercise(task):
    report = {'task': task, 'kind': 'deployment_fixture', 'modelCalls': 0,
              'isolation': isolation(), 'calls': [], 'completedJobs': []}
    device = DEVICES[task]
    async with streamablehttp_client('http://qsim:8123/mcp') as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = [tool.name for tool in (await session.list_tools()).tools]
            assert not any('syndrome_controller' in name for name in names), names
            report['tools'] = names

            async def call(name, **arguments):
                result = await session.call_tool(name, arguments)
                texts = [item.text for item in result.content if item.type == 'text']
                assert not result.isError, (name, texts)
                value = json.loads(texts[0]) if texts else result.structuredContent
                assert isinstance(value, dict), (name, value)
                assert not value.get('error'), (name, value)
                report['calls'].append(name)
                return value

            async def job(name, **arguments):
                submitted = await call(name, device_id=device, **arguments)
                job_id = submitted['job_id']
                deadline = time.monotonic()+180
                while time.monotonic() < deadline:
                    value = await call('get_job_result', job_id=job_id)
                    if value['status'] == 'complete':
                        report['completedJobs'].append(job_id)
                        if value.get('data') is None:
                            file = Path('/qsim_logs/public_job_results/results')/(job_id+'.json')
                            assert file.is_file(), value
                            report.setdefault('offloadedResults', []).append(str(file))
                            return json.loads(file.read_text())
                        return value
                    assert value['status'] != 'failed', value
                    await asyncio.sleep(0.5)
                raise TimeoutError('Public qsim job did not finish: '+job_id)

            await call('get_observable_spec' if task == 'adaptive_clustered_clbcs_h2o' else 'get_device_spec', device_id=device)
            if task == 'time_budgeted_hamlearn_10q':
                await job('run_hamiltonian_probe_batch', rows=[{'initial_state':['z+']*10,
                    'evolve_time_us':0.1, 'observable_pauli':'XIIIIIIIII'}])
                answer = {'task_id': task, 'hamiltonian_convention':'U(t)=exp(-i t/2 sum omega_P P)',
                    'term_order_convention':'one_local_xyz_then_edge_local_xx_xy_xz_yx_yy_yz_zx_zy_zz',
                    'num_terms':111, 'omega_vector_raw_rad_per_us':[0.0]*111,
                    'omega_vector_raw_rad_per_us_1sigma':[0.3]*111,
                    'activity_summary':{'schema_version':2,'verifiable':{'accepted_probe_rows':1,
                        'total_accepted_evolution_time_us':0.1,'min_accepted_evolve_time_us':0.1,
                        'max_accepted_evolve_time_us':0.1},'trajectory':{'protocol':'fixed_design',
                        'fit_model':'other','trajectory_details':NOTE}}}
            elif task == 'time_budgeted_shadow_surrogate_60q':
                await job('run_basis_shots', blocks=[{'x':[0.0]*6,'settings':[{'basis':'z'*60,'shots':64}]}])
                reveal = await call('lock_measurements_and_reveal_challenge', device_id=device)
                answer = {'predictions_as_measured':[[0.0]*1770 for _ in range(40)],
                    'challenge_id':reveal['challenge_id'], 'target_inputs_sha256':reveal['target_inputs_sha256'], 'method':NOTE}
            elif task == 'adaptive_clustered_clbcs_h2o':
                scheme = {'mixture_weights':[1/16]*16, 'local_basis_probabilities_xyz':[[[1/3]*3 for _ in range(14)] for _ in range(16)]}
                await call('evaluate_composite_scheme', device_id=device, **scheme)
                await job('run_pilot_measurements', settings=[{'basis':'Z'*14,'shots':64}])
                production = await job('execute_locked_composite_scheme', **scheme, control_variate_entries=[])
                data = production.get('data', production)
                answer = {'track_a':scheme,'track_b':{'request_digest':data['request_digest']},
                    'track_b_result':{'energy_raw_hartree':0.0,'uncertainty_hartree_1sigma_cluster':1.0},'method_summary':NOTE}
            elif task == 'logical_cnot_decoder_calibration':
                # Official replay requires at least 500 observed shots for
                # memory and each of the eight CNOT battery entries.
                await job('run_memory_experiment', layout='d5', rounds=12, shots=512)
                for config in ['z','x']:
                    for logical_input in ['00','01','10','11']:
                        await job('run_lattice_surgery_cnot', config=config, logical_input=logical_input, shots=512)
                public = Path('/task_materials')
                memory = json.loads((public/'memory_d5_scoring.json').read_text())
                cnot = json.loads((public/'cnot_superset.json').read_text())
                def dem(graph):
                    return [{'detectors':item['detectors'],'p':item['p_nominal'],
                             'flips_observables':item['flips_observables']} for item in graph]
                # Keep one public nominal mechanism per detector set, merging
                # the public output labels. This is not a fitted decoder.
                mechanisms = {}
                for config in cnot['configs'].values():
                    for edge in dem(config['matching_graph_nominal']):
                        key = tuple(sorted(edge['detectors']))
                        if key in mechanisms:
                            edge['flips_observables'] = sorted(set(edge['flips_observables'])|set(mechanisms[key]['flips_observables']))
                        mechanisms[key] = edge
                answer = {'task_id':task,'method':NOTE,'stage_a_mode':'device_probe','probed_spec':{},
                    'stage_b_mode':'memory_characterization','shots_for_memory_characterization_raw':512,
                    'dem_memory_d5':dem(memory['matching_graph_nominal']),
                    'decoder_config_memory':{'decoder_type':'mwpm','options':{}},
                    'self_measured_memory_logical_rate_raw':0.1,'lambda_d3_d5_raw':1.0,'memory_characterization_note':NOTE,
                    'stage_c_mode':'surgery_characterization','shots_for_surgery_characterization_raw':4096,
                    'dem_cnot_spacetime':list(mechanisms.values()),'decoder_config_cnot':{'decoder_type':'mwpm','options':{}},
                    'self_measured_cnot_error_raw':0.1,'surgery_characterization_note':NOTE,'stage_d_mode':'submit_decoders'}
            else:
                # Fifteen completed jobs are required before official physics
                # replay. Repeated idle probes satisfy only this technical gate.
                for _ in range(15):
                    await job('run_flux_pulse', coupler_flux=0.3, programmed_flux_q1=[0.0]*90,
                              sample_dt_ns=0.4, prep_ops=[], post_ops=[], idle_ns=0.0, measure_qubits=[1,2], shots=64)
                answer = {'task_id':task,'method':NOTE,'stage_a':{
                    'alpha_2_mhz_raw':-300.0,'alpha_2_mhz_1sigma':1.0,'coupling_j_mhz_raw':1.0,'coupling_j_mhz_1sigma':1.0,
                    'avoided_crossing_gap_mhz_raw':2.8,'crossing_flux_q1_raw':0.2,'coupler_decoupling_flux_raw':0.3,
                    'idle_zz_khz_raw':1.0,'idle_zz_khz_1sigma':1.0,'short_settling_amplitudes_raw':[0.1],
                    'short_settling_tau_ns_raw':[10.0],'characterization_method':'chevron_coupler_sweep_plus_cryoscope'},
                    'stage_b':{'coupler_idle_flux':0.3,'coupler_gate_flux':0.3,'pulse_family':'net_zero_smooth',
                    'intended_flux_samples':[0.0]*90,'programmed_dac_samples':[0.0]*90,'dac_bits':16,'sample_dt_ns':0.4,
                    'gate_time_ns':36.0,'net_zero_satisfied':True,'virtual_z_q1_rad':0.0,'virtual_z_q2_rad':0.0,
                    'predicted_conditional_phase_rad':0.0,'predicted_leakage_raw':0.1,'idle_zz_handling':'coupler_null'},
                    'stage_c':{'measured_conditional_phase_rad_raw':0.0,'measured_conditional_phase_rad_1sigma':0.1,
                    'measured_leakage_raw':0.1,'measured_leakage_1sigma':0.1,'gate_infidelity_raw':0.5,'gate_infidelity_1sigma':0.1,
                    'predistortion_residual_raw':0.0,'measured_idle_zz_khz_raw':1.0,'measured_idle_zz_khz_1sigma':1.0,
                    'verification_protocol':'conditional_phase_ramsey','leakage_input_set':'four_comp_basis'}}
            if task in ('time_budgeted_hamlearn_10q','time_budgeted_shadow_surrogate_60q'):
                path = Path('/submission/compatibility-probe.json')
                path.write_text(json.dumps(answer, allow_nan=False))
                receipt = await call('submit_final_answer', task_id=task, answer_file=path.name,
                                     answer_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            else:
                receipt = await call('submit_final_answer', task_id=task, answer=answer)
            report['submission'] = receipt
    return report


if __name__ == '__main__':
    print(json.dumps(asyncio.run(exercise(sys.argv[1])), indent=2))
