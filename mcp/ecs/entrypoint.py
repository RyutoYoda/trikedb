"""S3-backed shared MCP server. Credentials come from the ECS task role."""
import os


def command(env):
    graph = env.get('TRIKEDB_GRAPH_URL', '')
    if not graph.startswith('s3://') or '/' not in graph[5:]:
        raise ValueError('TRIKEDB_GRAPH_URL must name an s3://bucket/key.yaml object')
    token = env.get('TRIKEDB_TOKEN')
    issuer = env.get('TRIKEDB_OAUTH_ISSUER')
    if not token and not issuer:
        raise ValueError('Configure TRIKEDB_TOKEN or TRIKEDB_OAUTH_ISSUER')
    args = ['trikedb', 'serve', graph, '--host', '0.0.0.0',
            '--port', env.get('PORT', '8080'), '--stateless']
    if token:
        args += ['--token', token]
    if issuer:
        args += ['--oauth-issuer', issuer]
    if env.get('TRIKEDB_PUBLIC_URL'):
        args += ['--public-url', env['TRIKEDB_PUBLIC_URL']]
    elif issuer:
        raise ValueError('TRIKEDB_PUBLIC_URL is required for OAuth')
    return args


if __name__ == '__main__':
    args = command(os.environ)
    os.execvp(args[0], args)
