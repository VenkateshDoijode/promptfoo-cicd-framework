pipeline {
    agent {
        docker {
            image 'node:20-slim'
        }
    }

    environment {
        // Add OPENAI_API_KEY in Jenkins: Manage Jenkins → Credentials → Secret text
        OPENAI_API_KEY = credentials('OPENAI_API_KEY')
    }

    stages {

        stage('Install Promptfoo') {
            steps {
                sh 'npm install -g promptfoo'
                sh 'promptfoo --version'
            }
        }

        stage('LLM Quality Eval') {
            steps {
                sh '''
                promptfoo eval \
                    --config promptfooconfig.yaml \
                    --no-cache \
                    --output results/eval-results.json \
                    --fail-threshold 0.8
                '''
            }
            post {
                always {
                    archiveArtifacts artifacts: 'results/eval-results.json', allowEmptyArchive: true
                }
                failure {
                    echo 'LLM Eval failed — pass rate dropped below 80%. Check results artifact.'
                }
            }
        }

        stage('LLM Red Team Safety Scan') {
            when {
                branch 'main'
            }
            steps {
                sh '''
                promptfoo redteam run \
                    --config redteam.yaml \
                    --no-cache \
                    --output results/redteam-results.json
                '''
            }
            post {
                always {
                    archiveArtifacts artifacts: 'results/redteam-results.json', allowEmptyArchive: true
                    echo 'Red team scan complete. Review results artifact manually.'
                }
            }
        }

    }

    post {
        always {
            echo 'Pipeline complete. Download artifacts from Jenkins build page.'
        }
    }
}
