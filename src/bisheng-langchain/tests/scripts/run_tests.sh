#！/bin/bash
#!//bin/bash

function test_chat_sparkai() {
  export xunfeiai_appid="bb712a3d"
  export xunfeiai_api_key="a100393f4e16f7ac1f51d4d560061193"
  export xunfeiai_api_secret="MDRjZTcwODkwODE5Y2JhYzk3OWI5YjY4"
  PYTHONPATH=. python3 tests/test_chat_sparkai.py
}

# test_chat_sparkai

RT_EP=192.168.106.20:9001 PYTHONPATH=. python3 tests/test_chat_host_llm.py
