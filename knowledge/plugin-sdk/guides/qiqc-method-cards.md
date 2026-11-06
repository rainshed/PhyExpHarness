# QIQC 方法卡片参考

状态：开发参考，记录一组已有卡片及其实测结果，不规定改进策略。卡片尚未移植到本平台，未经 `candidate_check`，也未在本平台运行。本页只供人工阅读，不在 `build-knowledge.py` 的 `GUIDES` 中，不进入资料包，新活动的 Meta 通过 `sdk_read` 读不到。

## 内容与读法

本文收录 QIQC Challenge 自建 harness `stack-h16` 中的 5 张任务卡（CNOT、H2O、60q、hamlearn、CZ v3）、2 张原型卡（estimate、calibrate）和 1 组分析规则（扣除零信号参考、按实际到达的控制量拟合），并说明 8 个与具体方法无关的 [hook](#hook)（不含代码）。

卡片是给 Solver 的建议文本，是否遵循由 Solver 决定。每张卡的“阅读信息”写的是设计意图，不代表已验证的效果；效果只看下文证据。

**语言选择：**说明文字用中文，卡片正文保留英文原文。测得的数字来自英文文本，翻译相当于换了一份未测试的提示；公式和物理术语也更不容易走样。正文只去掉了 `# Component:` 标题行，除下述 CNOT 卡外与 `stack-h16` 的 `prompt-router/prompts/` 逐字相同；分析规则取自 `null-control-check-v2` 的注入文本。

**CNOT 卡与测试文本不同：**该卡有几句话超出公开任务说明，本文未收录，删除处标为 `[已删去]`。下文的 CNOT 数字都来自未删减的文本，删减后的版本没有测试过，不能沿用这些数字。

## 局限

- **不是 HY4。**全部运行都是 Sonnet 5 跑公开任务，没有一个数字来自 HY4，也不能外推到 HY4。
- **样本小。**每组只有 3 到 4 次，3/4 和 4/4 之间的差别不能当作真实差别。
- **增益是样本内的。**卡片是借助评分反馈、在这几个任务上开发的，下面的提升不是独立验证的结果。
- **卡片对隐藏任务没有帮助。**任务卡只在对应任务的公开特征命中时才发放；比赛 49 个任务中有 44 个隐藏。撤掉任务卡后的结果见[撤卡测试](#撤卡测试)。
- **CZ 没有解决。**最终 harness 上 CZ 仍是 0/4。

## 证据

全部为 Sonnet 5、公开任务。以下是观察结果；解释单独标明。

### 整体

四项开发任务，每组 16 次：

| 条件 | 通过 |
|---|---|
| 无插件 | 2/16 |
| 早期 harness（卡片加 hook） | 15/16 |

最终 harness，5 个任务：

| 任务 | `stack-h16`，自有循环 | H9，Claude Code（较早但相近的版本） |
|---|---|---|
| H2O | 4/4 | 3/3 |
| CNOT | 4/4 | 3/3 |
| 60q | 3/4 | 2/3 |
| hamlearn | 3/4 | 2/3 |
| CZ | 0/4 | 未包含在这组内 |
| 合计 | 14/20 | 10/12 |

`stack-h16` 这 20 次没有丢失答案。首次测量有 6 次运行因宿主网络中断而没有评分，已排除并重跑，14/20 只统计重跑批次。另有 `stack-h11` 在 Claude Code 上的 hamlearn 对照：4/4。

### CZ 的失败

| 条件 | 通过 |
|---|---|
| 无 v3 及之后的卡（其中 4 次为早期 v1 卡） | 0/42 |
| 卡片 v3 | 1/4 |
| 卡片 v4（增加验证步骤） | 0/4 |
| 卡片 v5 | 1/4 |
| v3 加“继续工作”规则 | 0/4 |

这些运行中第一阶段检查升至 40/48，但完整通过很少，门保真度仍是主要未达项。

解释：离线交叉测试显示 CZ 的失败出在分析而非测量，首要原因是没有扣除零信号参考。分析规则由此而来；它进入最终 harness 后 CZ 仍是 0/4，所以这条规则本身不足以让 CZ 通过。

### 撤卡测试

| 撤掉后保留的内容 | 通过 |
|---|---|
| 只留通用规则卡 | 0/12（CZ、60q、H2O 各 0/4） |
| 只留原型卡 | 0/8（60q、H2O） |
| 留一族撤卡（较早的测试） | 4/16 |

## 投递经验

- **卡片在提示中的位置有影响。**卡片最初按 Claude Code 投递上下文的方式测试，即紧贴任务说明。位置改变后效果不同，这一差异没有单独量化。迁移到其他提示结构后要重新测量。
- **中性的时间信号有帮助。**“已用 M / 共 T 分钟”这一提醒把 CZ 的第一阶段检查从 4/16 提到 12/16，hamlearn 维持 3/4，但 CZ 完整通过仍是 0/4。
- **自有循环上 hamlearn 从 1/4 到 3/4。**这期间同时做了三项改动：去掉紧迫的时间措辞、把超时命令转入后台、要求完整读取文件。三者没有分开测试，不能归功于其中任何一项。

`stack-h16` 的发放方式：提示路由器在启动前运行各卡的 SessionStart hook，把命中的卡写入系统提示，hook 本身仍注入一次，所以 Claude Code 上一张卡会到达两次。路由出错时不加卡，运行继续。任务卡看公开材料，CZ 卡和原型卡看任务说明，所有线索都命中才发放。

用 hook 的正则离线核对公开任务说明（未实际运行路由），原型卡命中情况如下：estimate 命中 H2O、hamlearn、CZ；calibrate 命中 CNOT、CZ；60q 两张都不命中。

## 与本平台格式的对应

我们的卡片是 Markdown 文本加 Python hook，走 Claude Code 的 hook 协议；本平台的插件是 ESM 模块或 `harbor-process-v1` 完整工程，用 `harness.json` 声明。这里只说明文本如何迁移，**没有实现移植**。

| 我们的做法 | 本平台的对应 |
|---|---|
| `prompts/*.md` 卡片文本 | 插件目录内的文本文件，由 `ctx.systemPrompt.section()` 加入；更换框架时由工程自行拼入提示 |
| SessionStart hook 按线索决定是否注入 | 入口读取 `PHYEXP_CONTEXT` 中的原始 instruction 和 workspace，决定是否装配该插件 |
| PostToolUse hook 记录 `CHECK` 行 | `tools/result` 观察结果，不改写结果 |
| 合并到一个 Claude Code 插件的 hooks | [`harness.json.plugins`](process-harness.md#插件用途机制与源码定位) 中逐个声明 |
| 卡片描述 | 目录内 `plugin.json` 的阅读字段，见[插件设计](plugin-design.md#为人提供用途和机制说明) |

下面是一条示意声明，未经构建：

```json
{"name":"cz-method","version":"3.0.0","path":"plugins/cz-method","config":{}}
```

提示位置会因此改变（见[投递经验](#投递经验)），上文的数字不能直接用于迁移后的版本。

## 卡片

### CNOT：`cnot-flag-method-v2`

对应任务 `logical_cnot_decoder_calibration`。

- `displayName`：格点手术解码器标定方法卡
- `functionSummary`：为解码器标定任务提供步骤建议：先拟合速率并拆分数据，再逐项检验观测标记，最后用留出数据复核提交内容。不提供任何数值。
- `mechanism`：公开材料含 `cnot_superset.json` 时把固定文本加入提示，每个会话一次。是否遵循由 Solver 决定，本插件不执行搜索，也不检查结果。本文文本有删减，见上文。
- `categories`：`prompt-context`

```text
LATTICE-SURGERY DECODER-CALIBRATION METHOD CARD. Applies when the task is: estimate the detector error models of a surface-code memory and of a lattice-surgery logical CNOT from raw detection events (a public detector superset, named parities folded into outputs by a byproduct-frame convention), scored by replay on fresh shots. Otherwise ignore it.
[已删去] Run every step below in code and print its result.

RATES, THEN A SPLIT.
- Fit rates on the public topology as the instruction describes (pair formula for two-detector edges, parity-identity residual for boundary mechanisms), pooled over the configurations that share a mechanism.
- Before looking at any error, split the shots of every configuration into a fit part and a held-out part. Search on the fit part only.

DIAGNOSE BEFORE TUNING.
- Decode the fit part and print the logical error per output and per battery entry. Compare the outputs that fold named parities in the frame convention with the outputs that fold none. [已删去]
- [已删去]

FLAG SEARCH.
- [已删去]
- Rank the boundary (single-detector) mechanisms by their FITTED rate; nominal rates can hide the ones that matter. Cover every mechanism whose fitted rate stands out from the bulk, not only the few largest.
- For each of them and each output of the z and x configurations, toggle the flag (add it if absent, remove it if present), decode the fit part with the toggled DEM and compare logical errors on the identical shots. Print one line per toggle: mechanism, output, direction, errors before and after.
- Keep a toggle only if the drop is significant after controlling false discoveries over all toggles tried (Bonferroni or FDR). Apply the best one, then repeat until no toggle helps.
- Do not call a residual error structural, irreducible or a floor until both directions have been tested for every high-rate boundary mechanism.

VALIDATE THE EXACT PAYLOAD.
- Before each submission, re-score the exact DEMs in the payload (not a pruned or rebuilt copy), memory and CNOT, on the held-out part. Print the battery average and the worst entry and compare them with the public floors.
- Declare flags with output names only, submit one mechanism per detector set, and never prune the DEM to shorten the submit call.
```

### H2O：`h2o-method-v4`

对应任务 `adaptive_clustered_clbcs_h2o`。

- `displayName`：复合阴影能量估计方法卡
- `functionSummary`：为 C-LBCS 能量估计任务提供按时间划分的日程、脚本化载荷、按显著性选择控制变量，以及按单次测量的完整方差选择 Track B 方案。卡中数字均来自公开说明或属于方法选择。
- `mechanism`：公开材料含带 `coefficient_hartree` 列的 CSV，或含 `track_a_warm_start` 的 `stale_notebook.json` 时，把固定文本加入提示，每个会话一次。日程和检查都是建议，由 Solver 决定是否遵循，本插件不强制。
- `categories`：`prompt-context`

```text
COMPOSITE-SHADOW (C-LBCS) ENERGY-ESTIMATION METHOD CARD. Applies when the task is: pick a 16-component locally-biased shadow scheme (Track A, public variance) and run one locked production with control variates (Track B) to estimate a Pauli-Hamiltonian energy. Otherwise ignore it.
Numbers below are per the public spec: 16 components, 14 qubits, 96 pilot settings / 24,576 pilot shots, production 192 settings x 256 shots, 192 control variates, 40 evaluate calls, 1800 s wall clock. Pacing is given as fractions of that wall budget.
Principle: choose, compare and lock the Track-B design on the true variance of the one-shot estimator, which includes the covariances of terms measured in the same shot, not on a sum of per-term variances; and list a control variate only where its mean is established beyond the noise of all the candidates tested.

HARD RULES
- Build every tool payload in code and send it through the Python mcp client. Never type or paste an array into a tool call: hand-typed payloads get cut off or mis-copied, and a re-typed control-variate list silently loses entries.
- Renormalise every mixture and every [component][qubit] row to sum to 1 (error < 1e-12, float64) in code before any call; hand-rounded probabilities are rejected.
- Never reuse the Track A scheme for Track B unchanged; Track B has its own objective (step 4).
- Run optimisers under `timeout 120`, each saving its best-so-far to a file. Start `date +%s > /tmp/t0` now and print elapsed minutes and the fraction of the wall budget used in every shell call.

SCHEDULE (fractions of the wall budget)
1. First tenth: read the Hamiltonian CSV and the warm start in the notebook. Write a short mcp client: connect, call a tool from a JSON file, poll get_job_result, print a short summary. Ignore the notebook's statistical advice.
2. By about a quarter: pilot submitted. 24-48 settings x 256 shots (+ one all-Z setting at 512, which covers every Z-only term and measures every Z-string used in step 4), bases sampled from the warm-start scheme, sent from a file. Leave the rest of the pilot budget unused until the means are printed. Optimise Track A in the background meanwhile. Pauli mean of term j = average parity over settings that cover it; keep N_j = covering shots.
3. By about half: Track A optimised and verified. Multi-start, >= 3 basins: warm start, uniform, coefficient-weighted (basis letters drawn in proportion to the c^2 mass on that letter per qubit); softmax parametrisation, L-BFGS or Adam on sum_j c_j^2/h_j (the local value matches evaluate to ~1e-9). Keep the best, renormalise exactly, send once through evaluate_composite_scheme. Stop polishing there.
4. By three fifths: Track B.
   (a) Control variates by significance, corrected for the number of candidates. Every non-identity Z-only term (letters Z and I only) is always listed, with its raw pilot mean. Every other term is a candidate: list it only if |raw pilot mean| * sqrt(N_j) exceeds the Bonferroni cut for the n_c candidates the pilot covered: the two-sided normal quantile at tail probability alpha / n_c, alpha a family-wise error rate of a few percent at most (statistics.NormalDist().inv_cdf gives it), so that the expected number of false entries stays well below one. The cut rises with n_c: recompute it whenever the candidate set changes, never set it by feel, never pad the list to 192. m_j = raw pilot mean on the list, 0 off it. Print n_c, the cut, the list length, the smallest listed z among the other terms and the largest rejected z.
   (b) The variance to minimise is the FULL within-setting variance W of one shot, not the diagonal sum_j c_j^2 (1 - m_j^2) / h_j: terms measured in the same shot are correlated. W = the sum, over ordered pairs (j, k) of non-identity terms (j = k included) whose X/Y letters sit on the same qubits with the same letters (the Z-only terms all pair with each other), of
       (c_j c_k / (h_j h_k)) * h_jk * (<Z_D> - m_j m_k)
     where h_jk = coverage probability of the union string (all letters of both terms; the same product form as h_j, so the same code and gradient pattern), D = the qubits where exactly one of the two terms has a Z (empty for j = k, where <Z_D> = 1 and h_jk = h_j), <Z_D> = mean parity of the bits on D over pilot shots whose basis is Z on every qubit of D. Pairs with different X/Y content are left out. The j != k part can be comparable to the j = k part and have either sign, so the diagonal sum alone can rank schemes wrongly.
   (c) Check W and its gradient before trusting them: a brute-force loop over a few pairs, finite differences on a random scheme. Then minimise W over the 16-component scheme with analytic gradients: one L-BFGS pass from your Track-A scheme and one from the diagonal-objective optimum; keep the lower W; do not hop. Print W with its j = k part and its j != k part for Track A and Track B (same m_j), and min_j h_j. Lock only if W(B) < W(A) and min_j h_j >= 1e-8 (a failed lock burns the lock budget). Never compare the diagonal sum alone: it can rise while W falls.
5. Verify the lock list in code before the call: len equals the file's length (never a short list from a copy slip), indices unique, in 1..1085, |mean| <= 1, payload read from the same file. Renormalise after any rounding and check every row sum (the mixture and each [component][qubit] row) against 1 within 1e-12 immediately before the lock call.
6. By about three quarters: locked production submitted and polled.
7. By five sixths: from the returned counts compute the energy and the cluster sigma with the pinned formula: z_bar_b over 256 shots, sigma = sqrt(sum_b (z_bar_b - z_bar)^2 / (192*191)); h_j from the locked scheme renormalised in float64. The reported energy and sigma must match the recomputation within 1e-4; never report the shot-IID error. Submit the answer from a script.
8. Remaining time: refine Track A only (production is single-shot), re-evaluate, resubmit; the last accepted submission counts.
9. If two thirds of the wall budget pass without a locked run, lock the best verified scheme with the control variates measured so far immediately.
```

### 60q：`shadow-method-v6`

对应任务 `time_budgeted_shadow_surrogate_60q`。

- `displayName`：闭合优先替代模型方法卡
- `functionSummary`：为隐藏线路关联预测任务提供步骤：先做试测和逐基矢零假设检验，分阶段设计，先拟合单比特均值，再检验每对比特的乘积形式，只对不通过的比特对单独拟合，并通过写答案的同一段代码验证。
- `mechanism`：公开材料同时含 `observable_index.json` 和 `target_challenge.json` 时，把固定文本加入提示，每个会话一次。是否遵循由 Solver 决定，本插件不执行拟合。
- `categories`：`prompt-context`

```text
CLOSURE-FIRST METHOD CARD. Applies when the task is: predict correlations of a hidden circuit at held-out inputs, where the response class is disclosed (bounded harmonic degree per input angle, bounded number of modes per response) and measurements are limited by a shot, job and wall-clock budget. Otherwise ignore it.
Principle: learn the structure first, spend the shots second. Run every check below in code, print its result and act on it before the next step. Do not plan the whole design in advance: the pilot decides it.

START (before any measurement call).
- Write a Python mcp client script first: generate payloads, poll and parse results in code; never hand-type or paste arrays.
- Read the disclosed form: the instruction, observable_index.json (response_class, hypothesis_class, physics, support semantics), target_challenge.json and get_device_spec. Write down what a response depends on, what bounds its harmonics and its mode count, what stays hidden and which caps bind.

LABELS (in the parser, before any test or fit).
- Compute every single-qubit mean and every pair correlator in float64 from the raw outcome strings: turn the outcome bits into plus or minus one as float64 before any sum or matrix product, never accumulate in an integer type, and pool repeated inputs by adding their shots.
- Check every label against its physical bounds, then print the label ranges and the count of violations: each mean and correlator lies in [-1, 1], and each pair's correlator lies between |a + b| - 1 and 1 - |a - b|, where a and b are its two qubits' means from the same shots. Estimates from the same shots obey these bounds exactly, so a violation is a bug in your code: fix it before any test or fit.

PILOT, THEN A NULL TEST PER BASIS (before any design).
- Run a small pilot at a handful of inputs (the all-zero input plus some random ones) in every fixed product basis ("x"*60, "y"*60, "z"*60) at equal shots. Use fixed bases, not random_pauli, so each basis can be tested. Keep each basis's statistics separate: never average the bases into the target observable at parse time.
- Test each basis against the binomial shot-noise expectation, for pair correlators and for single-qubit means: for s shots the variance of a noise-only estimate c is about one over s, so its s*c*c averages to one, and a pooled mean over N estimates has a standard error near the square root of two over N. Compare the pooled mean square with that, over targets and inputs, and test per target with a multiple-comparison allowance. A basis at the noise level carries no signal (confirm on a second small random set before dropping it); a basis clearly above it does.
- Drop null bases from the main design and give their shots to the bases that carry signal. A dropped basis contributes, for each pair, the product of its pooled single-qubit means (zero if those are null too).
- Print PILOT TEST: per basis, the pooled statistic against its noise expectation and the verdict. Submit no measurement beyond the pilot until that line is printed.

STAGES (a stage is one or more jobs submitted together; analyse the whole stage before submitting the next).
- Pilot, then at least one middle stage that settles the structure, then the final stage. After each stage print shots, jobs and elapsed seconds used. Start no large stage until the previous stage's per-basis test (and, once the data allow, its held-out excess) has been printed; size the next stage from what the last one showed.
- Prefer many distinct random, non-axis inputs to many shots per input: fit error follows the total shots, but recovering the support needs distinct inputs. A block holds one input, so the block cap limits inputs per job: submit a stage's jobs together so they simulate in parallel, and time them from elapsed_wall_clock_s in the results. Before the final stage refit on growing fractions of the inputs and require the held-out excess to flatten.
- Single-angle sweeps are cheap diagnostics for which angles a qubit depends on and with what degree; never use them as the main design or as validation.

MODEL, STEP ONE: EVERY SINGLE-QUBIT MEAN (in each basis that passed the test).
- Fit on random inputs only (every angle drawn). Keep the all-zero input and single-angle sweep points as diagnostics: where angles are fixed many columns coincide and mislead a greedy fit.
- Dictionary: integer frequency vectors m with every |m_k| at most the disclosed per-angle degree bound, one of each conjugate pair, as real columns cos(m dot x) and sin(m dot x) plus a constant, built by one function design(inputs, vectors) that the fit and the prediction both call. Order the vectors in shells of total degree (the sum of |m_k|) and start from the low shells; build wide dictionaries in batches because memory is limited.
- Estimator: weighted OMP. Weight each label by the inverse of its binomial variance taken at the fitted value, not at the noisy label (fit once with shot-count weights, then refit with the variance at that fit, floored away from zero); start from the constant; add the column most correlated with the weighted residual only while the weighted chi-square drops by more than a penalty that grows with the log of the number of columns searched; no fixed term count; respect the mode cap.
- Noise-calibrated stop: a qubit is resolved when its weighted chi-square lies within what shot noise alone gives (the chi-square distribution for its degrees of freedom, with a multiple-comparison allowance over all qubits) both on the inputs it was fit on and on held-out random inputs predicted by a fit without them. Refit each unresolved qubit on the next shells, up to the full per-angle box. If one stays unresolved, measure more random inputs before the lock, and meanwhile keep the shell whose fit predicts the held-out inputs best.
- Use this estimator and this stop as written: no fixed term count, no hold-out-only stop, no ridge or lasso in their place. Never take a support from single-angle sweeps; supports come only from the fit on random inputs. Print ESTIMATOR: per qubit and basis, the terms added, the weighted chi-square per degree of freedom and resolved yes or no, before the pair step.
- Print every qubit's fitted form (its frequency vectors with their cos and sin coefficients) and its chi-square per degree of freedom. Store each form as vectors and coefficients, never as positions in a separate label list, and check the round trip: the stored forms, evaluated through design() at the measured inputs, reproduce the fitted values.

MODEL, STEP TWO: PAIRS, CLOSURE FIRST.
- For every pair, in each basis that passed the test, the candidate prediction is the product of its two qubits' fitted forms. Test it per pair before fitting anything for that pair: the weighted chi-square of the pair's correlator labels against that product over all fit inputs (weights at the product), compared with the chi-square distribution for that many inputs with a multiple-comparison allowance over all pairs. Print how many pairs pass and how many fail.
- A pair that passes keeps the product. Fit a separate model only for each pair that fails: the disclosed class with the same estimator, weights, penalty, mode cap and stop, from the low shells; if it stays unresolved, keep whichever of it and the product predicts the held-out inputs better. Print the number of separate fits and their chi-square per degree of freedom.
- Run steps one and two as soon as the middle stage's data are in (they settle the structure and size the final stage), then again on all the data.

PREDICT AND VALIDATE THROUGH THE CODE THAT WRITES THE ANSWER.
- Write one prediction function from a list of inputs to the matrix of the scored observable: rows in input order, columns in observable_index.json pair order; per basis the products for the pairs that passed and the separate fits for the others; the observable formed from the basis correlators only here, exactly as the instruction defines it, including any average over bases (print the formula and one cell computed by hand next to the function's value) (a dropped basis contributes, for each pair, the product of its pooled single-qubit means, zero if those are null too); as measured, no readout mitigation; clipped to the physical range given in the instruction. Only this function writes the answer file.
- Validate through it: hold out random measured inputs (never sweep points), refit steps one and two on the rest, predict the held-out inputs with the same function and report the excess: held-out mean square minus the label-noise variance computed from the shots, as an RMSE in the units of the scored observable, overall and for the worst held-out input; compare it with the accuracy gate. A raw RMSE near the label noise says nothing about model error. Then refit on all inputs.
- While shots, jobs or wall clock remain, print BUDGET LEFT (shots, jobs, minutes) and spend them on new random inputs for the unresolved qubits and the failing pairs before any claim that the gate is out of reach.
- Do not call the gate out of reach until you have listed the unused information (null settings, structure shared across targets, unspent shots, estimator calibration) and computed the excess. If the excess exceeds the gate, change the model class or the design instead of stopping.

LOCK, SUBMIT EARLY FROM THAT FILE, THEN REFINE.
- Once the final stage is submitted, lock (admitted jobs can still be polled afterwards). Call lock_measurements_and_reveal_challenge, save the receipt to a JSON file from your client, write the answer file with the prediction function at its target inputs, and submit a valid answer at once with answer_file and its SHA-256; then refine and resubmit through the same function (the instruction caps submissions). The last accepted submission counts. Read the time from elapsed_wall_clock_s in each result and budget the wall clock backwards from the first submission.
- Before the first submission check that your transcript shows the per-basis null test, the stage log, the label bounds check, the fitted single-qubit forms, the closure counts and the held-out excess against the gate.
```

### hamlearn：`hamlearn-integrated-v2`

对应任务 `time_budgeted_hamlearn_10q`。

- `displayName`：哈密顿量学习综合方法卡
- `functionSummary`：为哈密顿量学习任务提供步骤：约定检查、设计检查、精确拟合、支撑集双向检验，先提交支撑集上的精确重拟合，再把剩余预算用于不确定度最大和接近阈值的项。
- `mechanism`：公开材料含名为 `hamiltonian*.json` 的字典文件时，把固定文本加入提示，每个会话一次。是否遵循由 Solver 决定，本插件不执行拟合和提交。
- `categories`：`prompt-context`

```text
HAMILTONIAN-LEARNING METHOD CARD. Applies when the task is: estimate a hidden coefficient vector over a public Pauli-term dictionary from time-evolution probe rows that return raw measurement outcomes, under a declared sparsity bound and coefficient-error gates. Otherwise ignore it.
Principle: the design sets the precision and the estimator keeps it. Run every step in code and print its result.
SPEC AND CONVENTION (before any probe).
- Print SPEC: the evolution-time budget, the accepted-row cap, their ratio (the mean evolve time at which the whole budget is spent within the row cap), the time grid, the coefficient bound, the sparsity bound, and the selection cut: the two-sided normal z value for a conventional family-wise level split over the number of dictionary terms (Bonferroni), computed by you. Design and support selection both use this cut.
- Convention test: on a few random rows that include y states and Y observables, compare your forward model and its derivatives with respect to the coefficients against a brute-force dense matrix exponential of the stated convention (the factor of one half included; its derivatives by central differences). Print CONVENTION: the largest difference; it must be at rounding level. Fix any sign or factor error before anything else.
- Loader: read each job's result by its job_id and match its rows by position to the rows you sent; assert that every returned observable and accepted time equals the one sent, before any fit (results paired in the wrong order look like a bad fit, not like an error).
DESIGN CHECK (before the main batch; seconds, in code).
- Sensitivity of a row to a term: the evolve time times the expectation of i times the term times the observable in the prepared state, zero unless the term anticommutes with the observable and every non-identity factor of that product is the prepared basis on its qubit (Pauli product rule).
- Coverage: a field component along one axis needs rows that prepare its qubit along a second axis and measure it along the third. A coupling is read through the measured site times the spectator's prepared eigenvalue, so prepare spectators with both signs (with one sign, fields and couplings move together) and in the bases the coupling needs (x or y spectators for X- and Y-type couplings).
- Times: the mean planned evolve time is at least the ratio from SPEC, with no bulk of rows at the shortest times.
- Precision: each planned row adds the outer product of its sensitivity vector, divided by the variance of its mean at zero coefficients (one minus the squared expectation, over the repetitions), to the information matrix of the plan. Print DESIGN: its rank, the worst predicted sigma per class (fields, couplings) with the worst terms, and the mean time. The plan passes when the rank is full and every term's predicted sigma times the selection cut is at or below the worst-coefficient (L-infinity) gate stated in the instruction: a term the size of that gate must clear the cut.
- If it does not pass, fix and recheck at most twice: random bases and both signs for spectators; rows with the missing prepare-measure pair for an uncovered class; longer times or more rows on the worst-determined terms. Then run the main batch with the best plan found. No synthetic studies or simulated datasets before the first probe.
ENGINE (before fitting).
- Build the Hamiltonian from the dictionary with bit-flip masks and phases, never Kronecker products of dense Paulis. For each parameter vector do one eigendecomposition and evaluate every row from it, batched by time.
- Exact Jacobian from the same eigenbasis: the propagator's derivative as an integral over the evolution, evaluated at a few Gauss-Legendre nodes (propagate the state forward to each node and the measured observable back, apply each dictionary term by its flip mask and phase), confirmed by doubling the nodes. Never finite differences over all coefficients.
- Print ENGINE: the time of one evaluation and of one Jacobian of all rows, and the projected time of a fit. Only if that is too slow, evaluate rows in light-cone windows (an exact eigendecomposition of the few sites around the observable).
- Fits run in the foreground, a few iterations per call, saving the vector, sigmas and chi-square to a file after each accepted step; warm-start every refit; stop when the relative chi-square change is small. Never end a turn while a fit is running; no process pools.
EXACT FIT.
- Weighted least squares on the row means of the raw outcomes, binomial variance from the model's own prediction refreshed every iteration, Levenberg-Marquardt over all dictionary terms from the first-order linear-response solution, coefficients inside the allowed range. Print FIT: the chi-square against its expectation (rows minus fitted parameters) with its tail probability. A fit far outside it is a wrong minimum or a convention error: fix that; such a fit is never submitted.
SUPPORT.
- Backward: drop the terms whose absolute estimate over sigma is below the selection cut from SPEC, refit exactly on the rest, repeat until stable. Forward: for each excluded term compute the conditional score statistic (squared score over its information with the included terms projected out); add the largest while it exceeds the square of the cut, refitting exactly after each addition. Alternate until nothing changes; print SUPPORT: each term moved and its statistic.
- The declared sparsity bound is a cap, never a target: never pad the support toward it; a step that would exceed it is not taken.
ANSWER.
- The first answer is the exact refit on the selected support (zeros elsewhere), submitted as soon as it exists; sigmas from its inverse information (zeroed terms: their full-fit sigma), clipped to the allowed range. Never submit the full fit, a first-order vector or notebook values, not even as a placeholder.
- Before every submission print SUBMIT: the support size against the bound, the mean binomial deviance per row of your rows under the vector you submit, and its chi-square against the expectation. Write the answer as a file directly under /submission and submit it with answer_file and the checksum of its exact bytes; a later submission replaces it.
SECOND STAGE.
- Keep part of the budget out of the main batch. After the first answer, spend the rest on rows aimed at the largest-sigma kept terms and the excluded terms nearest the cut, with the coverage rules above; then warm-start, refit, redo the support tests and resubmit after the SUBMIT print.
```

### CZ：`cz-method-v3`

对应任务 `tunable_coupler_cz_netzero`。最终 harness 使用 v3；v4、v5 没有更好的结果，未收录。

- `displayName`：已标定执行器分析方法卡
- `functionSummary`：为磁通脉冲门任务提供分析顺序：先表征线路阶跃响应，按留出预测选模型阶数，全部特征按实际磁通拟合，用差值求非谐性，强耦合处用三能级模型，并统一工作点、单位和参考系。不提供任何数值。
- `mechanism`：任务说明同时命中磁通、预失真或线路、CZ 或条件相位、DAC 或 AWG 或采样点四组线索时，把固定文本加入提示，每个会话一次。是否遵循由 Solver 决定，本插件没有提醒或拦截。
- `categories`：`prompt-context`

```text
CALIBRATED-ACTUATOR ANALYSIS v3 (method; no values are given here)

1. Line first. Characterize the flux line's step response before you use flux pulses to locate anything. Fit the
   cryoscope as a forward model, not by inverting rates point by point: for a flat programmed step of length N, the
   accumulated Ramsey phase is phase0 + B*N + C * (sum over n = 1..N of s[n]^2) on the quadratic sweet-spot arc, where
   s[n] is the instruction's discrete step response and B is the precession rate with the flux set to zero in the
   same sequence and frame. B is a fitted term; never divide raw rates or take ratios that still contain B. Pin B with
   zero-amplitude controls in the identical sequence: the same coupler bias, the same pulse-length grid and a played
   pulse whose samples are all zero. An idle delay or an empty pulse is a different control path and is not a valid
   zero. At long lengths B and the arc coefficient are degenerate, so the fit needs these controls; check that B from
   two different zero-amplitude lengths agrees before you fit the poles. The quadratic arc is a small-flux approximation: use it only for the cryoscope probe
   amplitude, never to convert flux to frequency far from the sweet spot.
2. Model order by prediction. Fit the step response with one, two and three poles; keep an extra pole only if it
   lowers the error on held-out pulse lengths beyond the noise. The pulse lengths must reach several times the slowest
   time constant you report. Keep the instruction's convention exactly (first realized sample is s[1]; tau from the
   discrete pole); do not force the amplitudes to sum to one.
3. Realized control everywhere. Once the line model is fitted, compute the realized flux of every pulse (sum of
   programmed increments times the step response) and fit every resonance, chevron and crossing against the realized
   flux, not the programmed value. Verify the line model by predicting a pulse you did not fit.
4. A frequency map valid over the whole flux range. For resonances far from the sweet spot, convert flux to frequency
   with the standard symmetric-transmon tuning law (frequency proportional to the square root of the absolute cosine of
   pi times the flux), its maximum taken from the device spec, and check it: it must place the single-excitation swap
   resonance (where the two qubit frequencies are equal) where your data put it.
5. Differences, not anchors. Get the second qubit's anharmonicity as a difference of two resonances measured the same
   way: the single-excitation swap (where the two qubit frequencies are equal) and the two-excitation crossing, both
   located on the realized-flux axis with the same frequency map. Never combine an absolute frequency from one method
   with an offset or frame from another. Check the sign (anharmonicity is negative) and that the result does not
   change when the frequency map is refitted.
6. Three levels near strong coupling. Where the coupling grows quickly with the coupler bias, fit chevrons with the
   three-level model of the states that share the excitation number, not a two-level Rabi formula. Fit J from the
   whole chevron (all detunings and durations) against the realized-flux detuning; the instruction's gap is
   two times the square root of two times J. Check J against a second estimate at the same coupler bias.
7. Report on the realized axis. Every flux you report (crossing, operating points) is the realized flux in units of the
   flux quantum, read from your realized-flux fit, not a programmed amplitude or a detuning.
8. One operating point, one value. Fields that name the same operating point must carry the same value; the coupler
   bias you park at for idling is the one you report as the decoupling point, chosen by the idle criterion the
   instruction scores.
9. Units and frames. For every converted quantity print its units, the frame it is in, and whether a rate is cyclic
   (in hertz) or angular (in radians per second; they differ by two pi). The instruction's frequencies and couplings
   are cyclic. Check the sign and the order of magnitude against a second, independent estimate before you use it.
```

### 原型卡：`archetype-estimate-v1`

- `displayName`：参数估计原型卡
- `functionSummary`：为“报告隐藏参数值”一类任务提供通用流程：列出参数和阈值、建立正向模型、试测、设计检查、拟合、结构检验、提交。
- `mechanism`：任务说明同时命中估计类、参数类和不确定度类线索时，把固定文本加入提示，每个会话一次。命中只靠关键词，可能误中；是否遵循由 Solver 决定。
- `categories`：`prompt-context`

```text
PARAMETER-ESTIMATION CARD. Applies when the answer reports values of hidden device or model parameters that the grader compares with hidden true values under error gates, and the tools run experiments whose settings you choose and return raw outcomes under a budget. Otherwise ignore it.
Run every step in code and print its line; report only values measured in this run.
PARAMS. List every scored parameter, its gate (absolute or relative) and every budget. Notebook and nominal values are priors to re-measure, never answers. Print PARAMS: parameter | gate | prior | experiment that measures it.
MODEL. One forward model mu(setting, theta) of the mean raw outcome in the instruction's exact conventions (factors of one half, signs, units, time indexing). Check it on a few settings against an independent brute-force computation, and its derivatives against central differences; assert each result matches the setting sent. Print MODEL: largest difference (rounding level).
PILOT. Early, spend a small share of the budget across every setting class; fit it for current values.
DESIGN, before the main spend, at the current values. For each planned setting s with N_s repeats: g_s = d mu_s / d theta; v_s = variance of one raw outcome (one minus mu squared for plus-minus-one outcomes). Information F = sum over s of N_s g_s g_s^T / v_s; sigma = square root of diag(inv(F)). Cut z = two-sided normal quantile for a family-wise error of a few percent split over the scored parameters. Pass: F has full rank and z * sigma <= gate for every parameter (relative gates at the current value). Else add settings that separate the parameters in the weakest eigenvector of F and lengthen the lever arm (time, amplitude, detuning) on the worst; recheck at most twice, then measure. Algebra only, no simulated datasets. Print DESIGN: rank | worst z * sigma / gate and its parameter.
FIT. Weighted least squares or maximum likelihood on the raw outcomes, model variances refreshed each iteration, from a linearised or grid start. Print FIT: chi-square vs its expectation (points minus parameters) and tail probability; if far outside, fix the minimum or the convention before any submission.
STRUCTURE. Keep a term, component or nonzero value only while |estimate| / sigma exceeds z on an exact refit; test removals and additions both ways; disclosed counts are caps, not targets. Print STRUCTURE: kept | dropped | added, with statistics.
ANSWER. Sigmas from inv(F) at the estimate. Submit the exact refit as soon as it exists, from a file written by code. Print ANSWER: each z * sigma / gate and any value equal to a prior. Spend the reserve on the largest ratios, refit, resubmit.
```

### 原型卡：`archetype-calibrate-v1`

- `displayName`：标定原型卡
- `functionSummary`：为“提交会被回放或施加的产物”一类任务提供通用流程：零参考、仪器模型、逆变换检查、可行性估算、在评分条件下测量、约定断言、提交测过的对象。
- `mechanism`：任务说明同时命中产物类和回放或实际到达类线索时，把固定文本加入提示，每个会话一次。命中只靠关键词，可能误中；是否遵循由 Solver 决定。
- `categories`：`prompt-context`

```text
CALIBRATION CARD. Applies when the answer is an artifact the grader replays or applies (a program, waveform, controller, decoder or error model) and the tools let you measure how the instrument responds to what you send. Otherwise ignore it.
Run every step in code and print its line; report only values measured in this run.
FRAME. First measure a null reference (the identity or idle setting) and express every later result relative to it. Print FRAME: null result and its noise.
INSTRUMENT. Model how the controls you send become what the device experiences. Fit it on long records; choose its order by the drop in chi-square per added parameter against that drop's expectation, never by the best fit alone. Print INSTRUMENT: order | chi-square drop per added term.
INVERSE. Build the inverse (predistortion, correction or decoder) from that model and check it: the model applied to the inverse of a target must return the target within noise. Print INVERSE: residual vs noise.
FEASIBILITY. Before tuning, compute from measured rates whether the required quality is reachable within the allowed time and amplitude. If it is not, change the design, not the tuning. Print FEASIBLE: predicted quality vs gate.
GRADED. Measure every graded quantity at the grader's own condition (the same settings, length, timing and input states the grader uses), not at a convenient proxy. Print GRADED: quantity | measured | gate.
CONVENTIONS. Write each convention the instruction states (signs, units, sample timing, phase references, frames) as an assertion in code that runs before every submission.
SUBMIT THE TESTED OBJECT. The answer is exactly the object you last measured, written by the same code; after any change, measure again before submitting. Print SUBMIT: fingerprint of the submitted object = fingerprint of the measured object.
```

### 分析规则：`null-control-check-v2`

适用于所有任务，包含两条规则：扣除零信号参考（NULL MAP），按实际到达的控制量拟合（REALIZED CONTROL）。

- `displayName`：零输入与实际控制量分析规则
- `functionSummary`：提醒 Solver 把零输入响应作为显式拟合项，并按实际到达系统的控制量拟合特征，同时打印可记录的检查行。不阻止提交。
- `mechanism`：会话开始时把两条规则注入一次；此后从工具输出中记录代码打印的 `CHECK NULL` 和 `CHECK CONTROL` 行（不读助手自己的文字）。本版本只注入和记录，不拒绝提交，也不判断物理上是否正确。
- `categories`：`prompt-context`、`tool-results`

```text
[null-control-check] Two general measurement rules apply to this task; apply them in your analysis from the first conversion on.
NULL MAP. Any conversion from a raw signal to a physical quantity (an accumulated phase or rate to a frequency or field, a ratio to an amplitude, counts to a population) carries the instrument's zero-input response. Measure that zero-input reference under the same conditions as the signal (same frame, same sequence, the control set to zero), make it an explicitly fitted term of your forward model, and push the zero-input data through the same pipeline. For each such conversion print from your code a line `CHECK NULL <name> value=<v> sigma=<s>`, where v is what the zero-input data map to and s its standard error; the conversion is valid when v is within about three sigma of zero. If the task has no such conversion, print `CHECK NULL none: <reason>`.
REALIZED CONTROL. If a control you program reaches the system through a transfer you have characterized or modelled (a filter, a settling or distortion response, a delay, crosstalk), fit every feature against the realized control computed from that transfer model, never against the programmed value. For each such fit print from your code `CHECK CONTROL <name> realized`, or `CHECK CONTROL <name> programmed: <reason>` if the transfer is negligible there. If there is no such transfer, print `CHECK CONTROL none: <reason>`.
```

## Hook

`stack-h16` 还有 8 个与具体方法无关的 hook。它们按 Claude Code 的 hook 协议编写，尚未移植。本页不收录代码，代码随我们的 AGPL 版本发布（这部分标注 AGPL-3.0-or-later）。

**没有一个 hook 单独测试过。**以下是全部 hook 共用的整体证据：

- 卡片加 hook 的 harness 为 15/16，无插件为 2/16。两者一起生效，无法拆开。
- 最终测量中 20/20 的答案被接受，hook 错误 0 次，丢失答案 0 次。

下面只有写明的才是单个 hook 的证据，其余 hook 只有这组整体证据。

迁移时，拒绝调用可能对应 `tools/pre-execute`，附加上下文可能对应 `tools/post-execute`。回合结束时的拦截没有核对到对应接口。

### `contract-check-v5`

- `displayName`：提交约定检查
- `functionSummary`：提交前按任务族的提交约定检查答案，并提供离线校验和从文件提交的命令行工具。不判断答案在物理上是否正确。
- `mechanism`：拦截提交调用，以及能定位到答案文件的脚本提交。确定会被拒收的硬错误每次都拒绝；软错误每会话最多拒绝 3 次，之后放行。定位不到文件时只提醒。检查本身出错时放行。部分规则依据公开的 verifier 和 simulator 源码编写，不含隐藏数值。
- `categories`：`execution-control`、`tools`、`prompt-context`
- **预防的失败：**答案不符合提交约定，到评分时才被拒收。
- **证据：**只有整体证据。

### `file-route-v2`

- `displayName`：大载荷文件通道
- `functionSummary`：提供一个助手，从 JSON 文件读取任务工具的参数并调用，把完整结果写入文件，只打印简短摘要。
- `mechanism`：会话开始时宣告一次，建议不要手打大载荷；是否使用由 Solver 决定。助手拒绝转发最终答案，答案走 `contract-check` 的提交助手。
- `categories`：`tools`、`prompt-context`
- **预防的失败：**手打的大答案超过 64k 输出上限而丢失。
- **证据：**CNOT 载荷有 138–186 KB，曾因此丢失，这是文件通道的由来。这是事故记录，不是对照测试。

### `submit-floor-v2`

- `displayName`：提交底线提醒
- `functionSummary`：快到时限仍没有答案被接受时，提醒 Solver 从文件提交当前最好的已验证答案。
- `mechanism`：每次工具调用后计算剩余时间。剩余时间不超过 5 分钟或时限的 10%（取较大者）且没有答案被接受时附加提醒，每会话最多 3 次，间隔至少 60 秒。首个答案被接受后提示一次可以继续改进。只提醒，不拒绝也不阻断。
- `categories`：`prompt-context`、`tool-results`
- **预防的失败：**到时限仍没有答案。
- **证据：**一次 60q 运行在时限前 26 秒才提交，因为 3 分钟的窗口对需要先锁定的任务太短，所以短任务的窗口改为 5 分钟。5 分钟这个值没有实测显示额外收益，只知道没有损害最终测量。

### `answer-before-wait-v4`

- `displayName`：等待前时间提示
- `functionSummary`：Solver 开始长等待而还没有答案时，给出一行中性的已用时间提示，不要求提交。
- `mechanism`：已用时间超过时限的 33% 后，识别 Bash、ScheduleWakeup、Agent 等调用中的长等待，放行调用并附加已用和总时长，以及后台运行长任务的建议。最多每 5 分钟一次，每会话 6 次。不阻断。
- `categories`：`prompt-context`、`tool-results`
- **预防的失败：**时间耗在等待上而没有答案。早期版本要求立即提交，在需要先锁定的任务上使 Solver 过早锁定，所以改为中性文字。
- **证据：**只有整体证据。[投递经验](#投递经验)中的时间提示测量不是对这个 hook 的单独测试。

### `answer-guard-v3`

- `displayName`：答案常识检查
- `functionSummary`：提交前对答案做与任务无关的常识检查，发现问题时警告。只警告，不拒绝。
- `mechanism`：检查非有限数值、非零项数达到公开的稀疏上限、复用公开 notebook 或先验中的数值、控制数组与实际发给设备的数组不符。答案被接受后又出现新测量时提示一次，说明答案没有用到这些数据。每会话最多 3 次警告、4 次提示。
- `categories`：`prompt-context`、`tool-results`
- **预防的失败：**提交照抄先验的值或没有测过的对象；最后一次答案之后的测量没有进入答案。
- **证据：**只有整体证据。

### `answer-consistency-v1`

- `displayName`：答案一致性检查
- `functionSummary`：提交前按任务说明写明的格式和答案自身的声明重新计算。格式不符时拒绝，声明不一致时警告。
- `mechanism`：读取答案和任务说明。格式项包括成对字段长度、采样点上限、常量、声明的长度、元素范围和有限数值；每项每会话最多拒绝 2 次，最后 3 分钟不拒绝。声明项（例如声称净零但数组之和不为零）只警告。
- `categories`：`execution-control`、`prompt-context`
- **预防的失败：**答案因格式无法评分，或与自身声明矛盾而未被发现。
- **证据：**回放 434 个已记录答案，格式拒绝只出现在 2 个已知无法评分的 CZ 答案上；声明警告出现在 8 个失败的 CZ 答案上，通过的答案没有触发。这是离线回放，没有测量它对通过率的影响。

### `no-background-agents-v4`

- `displayName`：禁止后台委派主任务
- `functionSummary`：不让 Solver 把主任务交给后台代理，也不让它在答案被接受之前结束回合。
- `mechanism`：拒绝后台子代理和委派整个实验与提交流程的前台子代理，其他前台子代理放行。没有答案被接受时阻止结束回合，每会话最多 2 次，之后放行。最终总结报告有未达标的自查项且剩余时间超过 20% 时也会阻止，与 `final-action-guard` 共用次数上限。
- `categories`：`execution-control`、`prompt-context`、`tool-results`
- **预防的失败：**把任务交给后台代理后结束回合，无头会话随之结束，没有提交答案。
- **证据：**早期一次 CZ 留出测试为 0/12，其中有运行因后台代理退出，也有其他原因，所以这个 0/12 不能全部归因于此。

### `final-action-guard-v2`

- `displayName`：最终动作前的记录检查
- `functionSummary`：要求 Solver 在不可逆调用或最后一次允许的提交之前，记录自己对每个通过门槛的当前数值。
- `mechanism`：会话开始时列出任务说明中的门槛和不可逆工具。不可逆调用缺少比最新设备结果更新的记录时，每个工具拒绝一次；剩余时间少于 20% 或 5 分钟（取较大者）时不拒绝。答案被接受后，若有更新的设备活动，或最后一次答案没有对应记录，会阻止结束回合，并设有次数上限。记录的数值由 Solver 自己填写，本 hook 不核实其真实性。
- `categories`：`execution-control`、`tools`、`prompt-context`
- **预防的失败：**没有核对门槛就做不可逆动作；在最后答案会封闭证据记录的任务上，答案之后的设备活动使运行作废。
- **证据：**
  - 曾有一条停止规则（S3）：记录的数值未达门槛时阻止结束。它让运行工作得更久，但没有带来更多通过，**所以已经移除**，现在只记录不阻止。保留的是记录要求和不可逆调用前的检查。
  - 后来因一次作废的答案加入了设备调用标记，**只有离线测试**。运行自己的 MCP 客户端脚本发起的调用不会被标记，要等结果文件出现后才能看到。
  - 其余只有整体证据。

## 许可

本仓库目前没有许可文件。提议本文收录的卡片文本采用 AGPL-3.0-only，与我们 harness 的循环主体一致，该许可只覆盖这部分文本，不涉及仓库其他内容。卡片在 harness 源码树中标注的是 AGPL-3.0-or-later。**待确认后定稿。**
