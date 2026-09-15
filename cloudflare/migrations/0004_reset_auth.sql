DELETE FROM auth_sessions;
DELETE FROM auth_users;
DELETE FROM sqlite_sequence WHERE name = 'auth_users';
