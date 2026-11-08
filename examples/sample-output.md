```text
examples/bad.ini:2: key or value appears before any section header
examples/bad.ini:5: option 'host' in section 'server' already exists
examples/bad.ini:6: section 'server' already exists
examples/bad.ini:7: key 'debug' has no value
examples/bad.ini:10: key 'bad line here' has no value
examples/configs/app.ini:5: option 'name' in section 'app' already exists
Checked 4 file(s), 6 problem(s) in 2 file(s).
```

Output of `sh examples/run-example.sh` — the checker on the whole
`examples/` folder. It exits 1, because the examples contain broken
files on purpose; the script itself exits 0.
