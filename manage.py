#!/usr/bin/env python3
"""One update manifest for all mods. Python standard library only."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit


def integer(value):
    return type(value) is int and 0 <= value <= 9_007_199_254_740_991


def validate(manifest):
    if type(manifest.get('schemaVersion')) is not int or manifest['schemaVersion'] != 1:
        raise ValueError('schemaVersion must be 1')
    products = manifest.get('products')
    if not isinstance(products, dict):
        raise ValueError('products must be an object')
    for product_id, product in products.items():
        if not re.fullmatch(r'[a-z0-9]+(?:[._-][a-z0-9]+)*', product_id):
            raise ValueError(f'Invalid product ID: {product_id}')
        if not isinstance(product, dict) or not isinstance(product.get('channels'), dict):
            raise ValueError(f'{product_id}: channels must be an object')
        for channel, policy in product['channels'].items():
            prefix = f'{product_id}/{channel}: '
            if not isinstance(policy, dict) or type(policy.get('enabled')) is not bool:
                raise ValueError(prefix + 'enabled must be true or false')
            minimum, latest = policy.get('minimumSupportedBuild'), policy.get('latest')
            if not integer(minimum) or not isinstance(latest, dict):
                raise ValueError(prefix + 'invalid minimumSupportedBuild or latest')
            build = latest.get('build')
            if not integer(build) or build <= 0 or minimum > build:
                raise ValueError(prefix + 'require 0 <= minimumSupportedBuild <= latest.build, build > 0')
            version, notes, link = latest.get('version'), latest.get('notes'), latest.get('url')
            if not isinstance(version, str) or not version.strip() or len(version) > 80:
                raise ValueError(prefix + 'invalid version')
            if notes is not None and (not isinstance(notes, str) or len(notes) > 4000):
                raise ValueError(prefix + 'notes must be text, at most 4000 characters')
            url = urlsplit(link) if isinstance(link, str) else None
            if url is None or url.scheme != 'https' or not url.hostname or url.username is not None or url.password is not None:
                raise ValueError(prefix + 'url must be a public HTTPS release link')
    if len(json.dumps(manifest).encode()) > 512 * 1024:
        raise ValueError('Manifest exceeds 512 KiB')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, default=Path(__file__).with_name('updates.json'))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('validate')
    release = sub.add_parser('release')
    release.add_argument('--product', required=True, help='Stable ID, e.g. nerogram-ios')
    release.add_argument('--channel', default='stable')
    release.add_argument('--name')
    release.add_argument('--version', required=True, help='Display label; not compared numerically')
    release.add_argument('--build', type=int, required=True)
    release.add_argument('--url', required=True, help='HTTPS link to the Telegram release post or download page')
    release.add_argument('--notes', default='')
    release.add_argument('--mode', choices=['recommended', 'required'], default='recommended')
    release.add_argument('--minimum-build', type=int, help='Override the mandatory threshold')
    disable = sub.add_parser('disable')
    disable.add_argument('--product', required=True)
    disable.add_argument('--channel', default='stable')
    args = parser.parse_args()
    manifest = json.loads(args.file.read_text())
    validate(manifest)
    if args.command == 'release':
        products = manifest['products']
        product = products.setdefault(args.product, {'name': args.name or args.product, 'channels': {}})
        if args.name:
            product['name'] = args.name
        previous = product['channels'].get(args.channel)
        if previous and args.build < previous['latest']['build']:
            raise ValueError('Build numbers must not decrease; disable the rule to cancel it')
        minimum = args.minimum_build
        if minimum is None:
            minimum = args.build if args.mode == 'required' else 0
        product['channels'][args.channel] = {
            'enabled': True, 'minimumSupportedBuild': minimum,
            'latest': {'build': args.build, 'version': args.version, 'url': args.url, 'notes': args.notes}
        }
    elif args.command == 'disable':
        manifest['products'][args.product]['channels'][args.channel]['enabled'] = False
    validate(manifest)
    if args.command != 'validate':
        # Do not leave a half-written manifest if saving is interrupted.
        fd, path = tempfile.mkstemp(prefix='.updates-', dir=args.file.parent)
        try:
            with os.fdopen(fd, 'w') as handle:
                handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
            os.replace(path, args.file)
        finally:
            if os.path.exists(path):
                os.unlink(path)
    print('OK:', args.file)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise SystemExit(str(error))
