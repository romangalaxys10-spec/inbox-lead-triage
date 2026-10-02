.PHONY: test mcp-smoke install-zcode install-claude install-antigravity agents-md install-all clean

SKILL := skills/inbox-lead-triage

test:
	ILT_HOME=$$(mktemp -d) python3 $(SKILL)/tests/run_tests.py

mcp-smoke:
	@printf '%s\n' \
	  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}' \
	  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
	  | ILT_HOME=$$(mktemp -d) python3 mcp/server.py | grep -c '"result"' | xargs -I{} sh -c '[ {} -ge 2 ] && echo "mcp-smoke OK ({} results)"'

install-zcode:
	./install.sh --zcode

install-claude:
	./install.sh --claude

install-antigravity:
	./install.sh --antigravity

agents-md:
	./install.sh --agents-md

install-all:
	./install.sh --all

clean:
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
