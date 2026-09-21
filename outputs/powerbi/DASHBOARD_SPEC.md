# Power BI dashboard specification - ITAC loan interest testing

## Data model (star schema)

| Table | Grain | Key | Notes |
|---|---|---|---|
| `fact_exceptions` | one row per loan x period x metric breaching tolerance | `exception_id` | `metric` in {interest, penal_charge, closing_principal, closing_balance} |
| `fact_control_impact` | one row per exception loan x attributed control | (`loan_id`, `control_key`) | rupee impact allocated without double counting pairs |
| `dim_loan` | loan | `loan_id` | product, branch, region, disbursal, principal, tenure, moratorium, attribution status |
| `dim_product` | product | `product_code` | product master (convention, reset frequency, spread history) |
| `dim_control` | control or control combination | `control_key` | C-01..C-09, two-control combinations, UNEXPLAINED/AMBIGUOUS |
| `dim_period` | billing month | `period_key` (yyyymm) | calendar and Indian financial year (Apr-Mar) attributes |

Relationships (single direction, many-to-one, from fact to dimension):
`fact_exceptions[loan_id] -> dim_loan[loan_id]`, `fact_exceptions[product_code] -> dim_product[product_code]`,
`fact_exceptions[control_key] -> dim_control[control_key]`, `fact_exceptions[period_key] -> dim_period[period_key]`,
`fact_control_impact[loan_id] -> dim_loan[loan_id]`, `fact_control_impact[control_key] -> dim_control[control_key]`,
`dim_loan[product_code] -> dim_product[product_code]`.

Mark `dim_period` as the date-like table for time intelligence (sort `period` by `period_key`, `month_name` by `month`).

## Measures (DAX)

```DAX
Exception Rows        = COUNTROWS ( fact_exceptions )
Exception Loans       = DISTINCTCOUNT ( fact_exceptions[loan_id] )
Exception Loan-Periods =
    COUNTROWS ( SUMMARIZE ( fact_exceptions, fact_exceptions[loan_id], fact_exceptions[period_key] ) )
Interest Difference   = CALCULATE ( SUM ( fact_exceptions[difference_inr] ), fact_exceptions[metric] = "interest" )
Penal Difference      = CALCULATE ( SUM ( fact_exceptions[difference_inr] ), fact_exceptions[metric] = "penal_charge" )
Income Impact (Net)   = [Interest Difference] + [Penal Difference]
Allocated Impact      = SUM ( fact_control_impact[impact_inr] )
Allocated Impact Gross = SUMX ( fact_control_impact, ABS ( fact_control_impact[impact_inr] ) )
Loans in Population   = COUNTROWS ( dim_loan )
Exception Rate        = DIVIDE ( [Exception Loans], [Loans in Population] )
```

Use `Allocated Impact` for anything sliced by control (it splits two-fault loans); use `Income Impact (Net)` for
period/product trends (it sums the actual differences in the exception rows).

## Pages

1. **Overview** - cards: Loans in Population, Exception Loans, Exception Rate, Exception Loan-Periods, Allocated Impact,
   Allocated Impact Gross. Donut: `dim_loan[attribution_status]`. Table: `dim_control` with conclusion and
   deficiency classification (conditional formatting: Deficient = red).
2. **Exceptions by control and product** - clustered bar: Exception Loans by `dim_control[control_name]`; matrix:
   rows `dim_control[control_key]`, columns `dim_product[product_code]`, values Exception Loans (heat-map formatting).
   Slicers: product, region, metric.
3. **Rupee impact** - bar: Allocated Impact and Allocated Impact Gross by control (net vs gross side by side - shows
   offsetting errors in C-01 and C-02); waterfall: Allocated Impact by control to total.
4. **Trend over time** - line: Exception Loan-Periods by `dim_period[period]`, legend `dim_control[control_key]`
   (C-02 spikes after the 2022-23 hiking cycle and the 2025 cuts; C-09 is confined to 2024; C-07 starts Oct-2023).
   Column: Income Impact (Net) by `dim_period[financial_year]`. Slicer: financial year.
5. **Top exceptions** - table: top 50 loans by ABS(Allocated Impact) with product, root cause, first/last exception
   period; drill-through to a **Loan detail** page showing expected vs system per period for the selected metric.

## Notes for reviewers
- Amounts are INR; format as `"₹"#,##0`.
- `difference_inr` = system - expected (positive = income overstated / customer overcharged).
- Refresh: rerun `python run_all.py`; the CSVs are regenerated deterministically (fixed seeds).
