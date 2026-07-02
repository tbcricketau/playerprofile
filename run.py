import sys
from streamlit.web import cli as stcli

if __name__ == '__main__':
    sys.argv = ["streamlit", "run", "app.py", "--server.port=8060"]
    sys.exit(stcli.main())
