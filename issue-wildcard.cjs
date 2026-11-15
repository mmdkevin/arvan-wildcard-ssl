const { spawnSync } = require('node:child_process');
const { copyFileSync, constants, existsSync, mkdtempSync, renameSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');

function required(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Set ${name} before running the script.`);
  return value;
}

function parseDomains(input) {
  const domains = new Set();
  for (const item of input.split(/[\s,]+/).filter(Boolean)) {
    const domain = item.toLowerCase().replace(/^\*\./, '').replace(/\.$/, '');
    const labels = domain.split('.');
    const validLabel = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
    if (domain.length > 251 || labels.length < 2 || !labels.every(label => validLabel.test(label))) {
      throw new Error(`Invalid domain: ${JSON.stringify(item)}. Use a DNS name such as example.com.`);
    }
    domains.add(domain);
  }
  if (!domains.size) throw new Error('Enter at least one domain.');
  return [...domains];
}

function run(program, args, options = {}) {
  const result = spawnSync(program, args, { stdio: 'inherit', ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${program} failed (${result.signal || `exit ${result.status}`}).`);
  }
}

function main() {
  const domains = parseDomains(process.argv.slice(2).join(' '));
  const email = required('ACME_EMAIL');
  const recipient = required('AGE_RECIPIENT');
  const token = required('ARVANCLOUD_API_KEY').replace(/^Apikey\s+/i, '');
  if (!/^\S+$/.test(token) || /^Apikey$/i.test(token)) {
    throw new Error('ARVANCLOUD_API_KEY must contain the ArvanCloud API key.');
  }
  delete process.env.ARVANCLOUD_API_KEY;

  const environment = process.env.ACME_ENV || 'staging';
  const includeApex = process.env.INCLUDE_APEX || 'true';
  if (!['staging', 'production'].includes(environment)) {
    throw new Error('ACME_ENV must be staging or production.');
  }
  if (!['true', 'false'].includes(includeApex)) {
    throw new Error('INCLUDE_APEX must be true or false.');
  }

  const output = resolve(`wildcard-${environment}.tar.gz.age`);
  if (existsSync(output)) throw new Error(`Move the existing output before running again: ${output}`);

  const names = domains.flatMap(domain =>
    includeApex === 'true' ? [domain, `*.${domain}`] : [`*.${domain}`]
  );
  const server = environment === 'production' ? 'letsencrypt' : 'letsencrypt-staging';

  // Validate the recipient before creating a certificate order.
  run('age', ['--encrypt', '--recipient', recipient], {
    input: Buffer.alloc(0),
    stdio: ['pipe', 'ignore', 'inherit'],
  });

  const work = mkdtempSync(join(tmpdir(), 'arvan-wildcard-'));
  try {
    run('lego', [
      'run', '--accept-tos', '--email', email, '--server', server,
      '--dns', 'arvancloud', '--path', work, '--cert.name', 'wildcard',
      '--domains', names.join(','), '--no-bundle=false',
    ], {
      cwd: work,
      env: {
        ...process.env,
        ARVANCLOUD_API_KEY: `Apikey ${token}`,
        ARVANCLOUD_PROPAGATION_TIMEOUT: process.env.ARVANCLOUD_PROPAGATION_TIMEOUT || '300',
      },
    });

    renameSync(join(work, 'certificates', 'wildcard.crt'), join(work, 'fullchain.pem'));
    renameSync(join(work, 'certificates', 'wildcard.key'), join(work, 'privkey.pem'));
    const archive = join(work, 'wildcard.tar.gz');
    const encrypted = `${archive}.age`;
    run('tar', ['-czf', archive, '-C', work, 'fullchain.pem', 'privkey.pem']);
    run('age', ['--encrypt', '--recipient', recipient, '--output', encrypted, archive]);
    copyFileSync(encrypted, output, constants.COPYFILE_EXCL);
    console.log(`Encrypted certificate bundle: ${output}`);
  } finally {
    rmSync(work, { recursive: true, force: true });
  }
}

try {
  main();
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
