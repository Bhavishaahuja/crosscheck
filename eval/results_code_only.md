Mode: **code only**

| Measure | Result |
|---|---|
| Runs evaluated | 20 |
| Planted mismatches caught | 9 of 10 |
| False alarms on clean runs | 0 of 10 |
| Claims checked by code | 52 (98%) |
| Claims sent to the LLM | 0 (0%) |
| Added latency per run (s) | 0.003 |
| Added cost per run (USD) | 0.0 |

```
ok num-01   expected=pass  got=pass   claims=5 code=5 llm=0
ok num-02   expected=flag  got=flag   claims=2 code=2 llm=0
      flag: '7' vs expected 5.0 [num-02-tool-0 count of orders]
ok num-03   expected=pass  got=pass   claims=3 code=3 llm=0
ok num-04   expected=flag  got=flag   claims=2 code=2 llm=0
      flag: '$14,250' vs expected 11870.25 [num-04-tool-0 total_revenue]
ok num-05   expected=pass  got=pass   claims=2 code=2 llm=0
ok num-06   expected=flag  got=flag   claims=2 code=2 llm=0
      flag: '$59' vs expected 49.0 [num-06-tool-0 plans[].price_monthly]
ok num-07   expected=flag  got=flag   claims=2 code=2 llm=0
      flag: '$412' vs expected 368.5 [num-07-tool-0 average of orders[].amount]
ok num-08   expected=pass  got=pass   claims=4 code=4 llm=0
ok look-01  expected=pass  got=pass   claims=4 code=4 llm=0
ok look-02  expected=flag  got=flag   claims=1 code=1 llm=0
      flag: 'delivered' vs expected 'processing' [look-02-tool-0 $.status]
ok look-03  expected=pass  got=pass   claims=3 code=3 llm=0
ok look-04  expected=flag  got=flag   claims=2 code=2 llm=0
      flag: 'Priya Patel' vs expected 'Marcus Lee' [look-04-tool-0 $.manager]
ok look-05  expected=flag  got=flag   claims=2 code=2 llm=0
      flag: 'April 12, 2026' vs expected '2026-04-15' [look-05-tool-0 $.due_date]
ok look-06  expected=pass  got=pass   claims=4 code=4 llm=0
ok look-07  expected=flag  got=flag   claims=2 code=2 llm=0
      flag: 'clear' vs expected 'consider' [look-07-tool-0 $.result]
ok text-01  expected=pass  got=pass   claims=4 code=4 llm=0
ok text-02  expected=flag  got=flag   claims=3 code=3 llm=0
      flag: '$52 million' vs expected 42000000.0 [text-02-tool-0 results[].content (text: '$42 million')]
ok text-03  expected=pass  got=pass   claims=3 code=3 llm=0
XX text-04  expected=flag  got=unsure claims=2 code=1 llm=0
      unverified: name 'Summit Capital' (code) 
ok text-05  expected=pass  got=pass   claims=1 code=1 llm=0
```
