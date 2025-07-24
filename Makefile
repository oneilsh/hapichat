.PHONY: install app

install:
	@echo "Installing dependencies..."
	poetry install --no-root

app:
	@echo "Running app..."
	poetry run streamlit run app.py