.PHONY: all install test app clean
all:
	python run_all.py
install:
	pip install -r requirements.txt
test:
	python -m pytest -q tests
app:
	streamlit run app/streamlit_app.py
clean:
	rm -rf data/generated/* data/ground_truth/* outputs/audit outputs/powerbi/* outputs/charts/* outputs/*.xlsx outputs/*.md outputs/*.json outputs/*.csv
