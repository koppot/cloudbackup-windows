import argparse
import sys
from linux.app import create_app

def detect_tailscale_ip():
    return '100.100.100.100'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/opt/adc-backup/config.yaml')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()

    ts_ip = detect_tailscale_ip()
    if not ts_ip:
        print("Error: Tailscale IP not found.")
        sys.exit(1)

    app = create_app(args.config)
    
    print(f"Starting ADC Backup System on {ts_ip}:{args.port}")
    app.run(host=ts_ip, port=args.port, debug=False)

if __name__ == '__main__':
    main()
