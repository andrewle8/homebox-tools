.PHONY: setup login

setup:
	pip install -r requirements.txt
	playwright install chromium
	mkdir -p ~/.config/homebox-tools
	@echo "Setup complete. Copy config/config.example.yaml to ~/.config/homebox-tools/config.yaml and edit it."

login:
	python -m homebox_tools --login
