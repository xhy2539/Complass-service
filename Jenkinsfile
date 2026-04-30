pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    stages {
        stage('Prepare Python Environment') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
                            set -eux
                            rm -rf .venv
                            (python3 -m venv .venv || python -m venv .venv)
                            . .venv/bin/activate
                            python -m pip install --upgrade pip
                            python -m pip install -r requirements.txt
                        '''
                    } else {
                        bat '''
                            if exist .venv rmdir /s /q .venv
                            py -3 -m venv .venv || python -m venv .venv
                            call .venv\\Scripts\\activate.bat
                            python -m pip install --upgrade pip
                            python -m pip install -r requirements.txt
                        '''
                    }
                }
            }
        }

        stage('Syntax Check') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
                            set -eux
                            . .venv/bin/activate
                            python -m compileall -q app
                        '''
                    } else {
                        bat '''
                            call .venv\\Scripts\\activate.bat
                            python -m compileall -q app
                        '''
                    }
                }
            }
        }

        stage('Application Import Check') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
                            set -eux
                            . .venv/bin/activate
                            python -c "from app.main import app; print(app.title)"
                        '''
                    } else {
                        bat '''
                            call .venv\\Scripts\\activate.bat
                            python -c "from app.main import app; print(app.title)"
                        '''
                    }
                }
            }
        }
    }
}
