# Evaluation report - ITAC interest testing engine

Scores the audit engine's output against the injected ground truth. The audit engine never saw these labels; nothing below was used to set its tolerance or hypotheses.

## Population

- Loans: 50,000; loan-periods in system ledger: 1,296,378
- Faulty loans injected: 1,430; with a numeric effect: 1,418
- Affected loan-periods (any change > INR 0.005): 28,402; of which above tolerance: 27,458

## Detection (tolerance: max(INR 1.0, 0.01% of expected))

| Level | Truth definition | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|---|
| Loan | any change | 1,416 | 0 | 2 | 100.0% | 99.9% |
| Loan-period | any change | 27,458 | 0 | 944 | 100.0% | 96.7% |
| Loan | change > tolerance | 1,416 | 0 | 0 | 100.0% | 100.0% |
| Loan-period | change > tolerance | 27,458 | 0 | 0 | 100.0% | 100.0% |

Loan-period recall against 'any change' is below 100% by design: many affected periods move by less than the tolerance (e.g. daily rounding error in a single month, or tiny balance drift). Against changes that exceed the tolerance, recall is the meaningful measure.

## Attribution

- Detected truly-faulty loans: 1,416
- Exact-match accuracy (attributed control set = injected control set): 99.8%
- Single-fault loans: 100.0%; double-fault loans: 93.3%
- Status counts: {'Attributed': 1415, 'Unexplained': 1}; ambiguous share 0.0%, unexplained share 0.1%

### Confusion matrix (rows: injected fault, columns: attributed; pairs grouped as PAIR)

| true_controls   |   C-01 |   C-02 |   C-03 |   C-04 |   C-05 |   C-06 |   C-07 |   C-08 |   C-09 |   PAIR |   UNEXPLAINED |
|:----------------|-------:|-------:|-------:|-------:|-------:|-------:|-------:|-------:|-------:|-------:|--------------:|
| C-01            |    176 |      0 |      0 |      0 |      0 |      0 |      0 |      0 |      0 |      0 |             0 |
| C-02            |      0 |    148 |      0 |      0 |      0 |      0 |      0 |      0 |      0 |      0 |             0 |
| C-03            |      0 |      0 |    177 |      0 |      0 |      0 |      0 |      0 |      0 |      0 |             0 |
| C-04            |      0 |      0 |      0 |    139 |      0 |      0 |      0 |      0 |      0 |      0 |             0 |
| C-05            |      0 |      0 |      0 |      0 |    140 |      0 |      0 |      0 |      0 |      0 |             0 |
| C-06            |      0 |      0 |      0 |      0 |      0 |    154 |      0 |      0 |      0 |      0 |             0 |
| C-07            |      0 |      0 |      0 |      0 |      0 |      0 |    146 |      0 |      0 |      0 |             0 |
| C-08            |      0 |      0 |      0 |      0 |      0 |      0 |      0 |    146 |      0 |      0 |             0 |
| C-09            |      0 |      0 |      0 |      0 |      0 |      0 |      0 |      0 |    145 |      0 |             0 |
| PAIR            |      0 |      0 |      0 |      1 |      0 |      0 |      0 |      1 |      0 |     42 |             1 |

### Every miss, explained

- **LN0015206** (HL-FLT): injected C-02+C-08, engine: C-08. Standalone effects INR {'C-02': 0.0, 'C-08': 6978.42}. Attributed to C-08 only. The other injected fault (C-02) changed no figure by more than the tolerance on its own (max standalone effect INR 0.00); e.g. a reset lag has no effect when the benchmark did not move between the two reset dates. No recalculation-based test can observe a fault that leaves the numbers unchanged.
- **LN0039154** (GL-FIX): injected C-01+C-08, engine: UNEXPLAINED. Standalone effects INR {'C-01': 3.5, 'C-08': 350.14}. Two faults interact inside the same billing period(s). The pair search solves the implied spread on top of the other hypothesis, but with too few periods the two effects are not separable, so no candidate reproduces the system figures within tolerance. Correctly left for manual follow-up.
- **LN0040092** (HL-MCLR): injected C-02+C-04, engine: C-04. Standalone effects INR {'C-02': 0.0, 'C-04': 7296.01}. Attributed to C-04 only. The other injected fault (C-02) changed no figure by more than the tolerance on its own (max standalone effect INR 0.00); e.g. a reset lag has no effect when the benchmark did not move between the two reset dates. No recalculation-based test can observe a fault that leaves the numbers unchanged.

### Faulty loans not flagged (loan-level false negatives)

| Loan | Injected | Metric with largest change | Period | Change (INR) | Tolerance applied (INR) |
|---|---|---|---|---|---|
| LN0023738 | C-05 | interest | 2024-09 | 5.95 | 7.59 |
| LN0031165 | C-06 | closing_principal | 2023-04 | 0.79 | 1.00 |

Both misses are tolerance effects, not recalculation errors. The C-06 case is a genuinely immaterial rounding drift. The C-05 case is a real weakness in the procedure design: capitalising a INR 750 penal charge moves closing principal by exactly INR 750, but on a INR 95.8 lakh home loan the relative leg of the tolerance (0.01% of balance ~ INR 958) is larger, and closing balance does not move at all because the charge is only reclassified from penal receivable to principal. Recommended change (not applied, to avoid tuning on ground truth): test the penal-receivable component separately with an absolute-only tolerance, since any capitalised penal charge is a regulatory breach regardless of size.


## Tolerance sensitivity

| Abs. tolerance (INR) | Loan precision | Loan recall | Loan-period precision | Loan-period recall | FP loan-periods |
|---|---|---|---|---|---|
| 0.01 | 100.0% | 99.9% | 100.0% | 96.9% | 0 |
| 0.1 | 100.0% | 99.9% | 100.0% | 96.9% | 0 |
| 0.5 | 100.0% | 99.9% | 100.0% | 96.8% | 0 |
| 1.0 | 100.0% | 99.9% | 100.0% | 96.7% | 0 |
| 5.0 | 100.0% | 99.7% | 100.0% | 94.1% | 0 |
| 25.0 | 100.0% | 92.9% | 100.0% | 84.3% | 0 |
| 100.0 | 100.0% | 87.7% | 100.0% | 73.5% | 0 |

False positives are zero at every tolerance because the auditor's rules and the client's correct configuration agree exactly on synthetic data. On real data, expect FPs from undocumented product features, manual adjustments and data-extraction issues; the tolerance exists for those. Recall falls as tolerance rises because small-value faults (daily rounding, short leap-year effects) disappear under the threshold.

## Misstatement

- Injected net income effect (system - correct, interest + penal): INR 5,193,105.35
- Injected gross interest error (sum of absolute differences): INR 11,957,407.49
- Detected net income effect on exception loans: INR 5,193,098.17 (100.0% of injected net)

| Control | Injected (single-fault loans) | Attributed by engine (incl. share of pairs) |
|---|---|---|
| C-01 | 1,821,879.05 | 1,877,768.54 |
| C-02 | -1,976,911.03 | -2,032,037.51 |
| C-03 | -19,356.59 | -18,148.34 |
| C-04 | 1,784,826.88 | 1,825,469.65 |
| C-05 | 187,649.64 | 211,296.56 |
| C-06 | -303.52 | -440.45 |
| C-07 | 2,320,686.11 | 2,431,337.39 |
| C-08 | 748,734.49 | 804,810.52 |
| C-09 | 83,855.20 | 92,685.06 |
| UNEXPLAINED | 0.00 | 356.75 |

Net figures hide offsetting errors (C-01 includes negative offsets; C-02 lags cut and raise rates depending on the rate cycle; C-06 rounding nets to ~zero). Gross error is the better measure of control failure.

## Runtime

`{'load_seconds': 1.87, 'recalculation_seconds': 0.82, 'comparison_seconds': 0.31, 'attribution_seconds': 3.82, 'total_seconds': 7.22}`

## Weaknesses to be honest about

- Auditor and client share `src/common` (day-count, rounding, EMI, rate lookup). A bug there would be invisible to the test - the same risk as an auditor re-using the client's own calculation logic. Unit tests on `common` against hand-computed values mitigate but do not remove it.
- The hypothesis library only contains fault types the auditor thought of. A novel fault would show as Unexplained - which is the correct audit outcome, but it means attribution accuracy here is an upper bound.
- Synthetic data is too clean: zero false positives will not hold on a real core banking extract.
- Faults with no numeric effect (e.g. a reset lag during a flat rate period) cannot be detected by any recalculation; they need a configuration review (ITGC / parameter testing).