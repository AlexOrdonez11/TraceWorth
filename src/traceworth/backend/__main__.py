"""Run the local API, bound exclusively to loopback."""
import argparse
import uvicorn
from .app import create_app


def main():
    parser = argparse.ArgumentParser(description='Run the TraceWorth local FastAPI backend.')
    parser.add_argument('--port', type=int, default=18766)
    parser.add_argument('--database', default='local-data/traceworth.db')
    parser.add_argument('--allowed-origin', action='append', help='Exact browser origin; repeat for multiple origins')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    uvicorn.run(create_app(args.database, args.allowed_origin), host='127.0.0.1', port=args.port, proxy_headers=False)


if __name__ == '__main__':
    main()
