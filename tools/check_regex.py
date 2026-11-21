import re
answer = open('/tmp/s1_answer.txt', 'w')
# Just test the regex pattern directly
test = "... bias is down. ... CALL: DOWN"
m = re.search(r"CALL\s*:\s*(UP|DOWN|NO-TRADE|NOTRADE)", test or "", re.IGNORECASE)
print("regex works:", m.group(1) if m else "NO MATCH")
