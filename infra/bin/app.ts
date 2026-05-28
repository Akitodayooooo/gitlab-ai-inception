import * as cdk from 'aws-cdk-lib';
import { GitlabStack } from '../lib/gitlab-stack';

const app = new cdk.App();

new GitlabStack(app, 'GitlabAiInceptionStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION ?? 'ap-northeast-1',
  },
  tags: {
    Project: 'gitlab-ai-inception',
    ManagedBy: 'cdk',
  },
});
