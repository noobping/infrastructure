# Infrastructure bootstrap, run through the upstream Rails runner as GitLab's user.
require 'json'
ApplicationSetting.current.update!(signup_enabled: false, default_project_visibility: 0,
                                  default_group_visibility: 0, default_snippet_visibility: 0)
value = JSON.parse(STDIN.read)['token']
token = value && PersonalAccessToken.find_by_token(value)
unless token && token.user_id == 1 && token.scopes == ['read_api'] &&
       !token.revoked? && token.expires_at && token.expires_at > Date.today + 30
  token&.revoke! if token&.name == 'infrastructure-idle'
  token = User.find(1).personal_access_tokens.create!(
    name: 'infrastructure-idle', scopes: ['read_api'], expires_at: Date.today + 365)
  value = token.token
end
puts JSON.generate({token: value})
