# Managed in the role image; keep private overrides in /etc/gitlab/private.rb.
external_url 'https://git.vm:8443'
nginx['listen_port'] = 8080
nginx['listen_https'] = false
letsencrypt['enable'] = false
gitlab_rails['gitlab_shell_ssh_port'] = 2222
gitlab_rails['gitlab_ssh_host'] = 'git-ssh.vm'
gitlab_rails['initial_root_password'] = File.read('/etc/gitlab/bootstrap-password').strip
gitlab_rails['initial_shared_runners_registration_token'] = nil
gitlab_rails['gitlab_default_projects_features_container_registry'] = true
registry_external_url 'https://git-registry.vm:8443'
registry_nginx['listen_port'] = 5050
registry_nginx['listen_https'] = false
# Use the filesystem registry backend, which gitlab-backup includes.
registry['database'] = { 'enabled' => false }
gitlab_rails['backup_keep_time'] = 604800
prometheus_monitoring['enable'] = false
alertmanager['enable'] = false
gitlab_pages['enable'] = false
gitlab_kas['enable'] = false
# NGINX owns 8080; Puma also defaults to that port upstream.
puma['port'] = 8081
puma['worker_processes'] = 2
sidekiq['concurrency'] = 10
postgresql['shared_buffers'] = '512MB'
logging['logrotate_frequency'] = 'daily'
logging['logrotate_rotate'] = 7
from_file '/etc/gitlab/private.rb' if File.exist?('/etc/gitlab/private.rb')
