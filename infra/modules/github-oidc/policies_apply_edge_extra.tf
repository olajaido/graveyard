# Apply role policy, part 3: the edge (spec infra-edge, EDGE-IAM-1 to EDGE-IAM-5, design 12.2). Route 53 records in the one
# existing hosted zone, the site bucket's objects, and the CloudFront alarms and topic in us-east-1. Every statement is limited
# to a graveyard-<env> name, except the Route 53 ones, which are exception E12.
locals {
  apply_edge_extra_docs = { for e in local.env_list : e => jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Exception E12 (infra-edge, maintainer-approved 25 Nov 2026): Route 53 supports no tag condition and the hosted zone has no
      # Graveyard name, so the resource is the exact zone ARN and the scoping is on what the request changes: only this env's record
      # names ("_*.<site host>" covers the ACM validation CNAMEs), only A, AAAA and CNAME records, only CREATE, UPSERT and DELETE. The Null condition makes the ForAllValues checks bite when a key is missing.
      {
        Sid      = "ExceptionE12"
        Effect   = "Allow"
        Action   = local.exception_actions.e12_route53_change
        Resource = [local.arn_zone]
        Condition = {
          "ForAllValues:StringLike" = { "route53:ChangeResourceRecordSetsNormalizedRecordNames" = local.edge_record_names[e] }
          "ForAllValues:StringEquals" = {
            "route53:ChangeResourceRecordSetsRecordTypes" = ["A", "AAAA", "CNAME"]
            "route53:ChangeResourceRecordSetsActions"     = ["CREATE", "UPSERT", "DELETE"]
          }
          # ForAllValues is true when the key is missing from the request. Every ChangeResourceRecordSets call carries all
          # three keys, and this makes the policy say so: a request without them is not allowed.
          Null = {
            "route53:ChangeResourceRecordSetsNormalizedRecordNames" = "false"
            "route53:ChangeResourceRecordSetsRecordTypes"           = "false"
            "route53:ChangeResourceRecordSetsActions"               = "false"
          }
        }
      },
      # Exception E14 (infra-edge, maintainer-requested 27 Nov 2026): a web ACL that references an AWS managed rule group needs
      # CreateWebACL and UpdateWebACL on the managedruleset resource type too. AWS managed rule sets have no Graveyard name and cannot
      # be tagged, so the resource is the one global pattern in us-east-1 and nothing else. The call is still authorised on the web
      # ACL itself, which only the Waf statement of the edge policy allows, and only for graveyard-<env>-* names.
      { Sid = "ExceptionE14", Effect = "Allow", Action = local.exception_actions.e14_waf_managed, Resource = [local.gen.managed_rule_sets] },
      { Sid = "Route53Read", Effect = "Allow", Action = local.act.edge_route53_read, Resource = [local.arn_zone] },
      # Terraform waits for a record change to reach INSYNC with GetChange. A change ID has no name; this is a read.
      { Sid = "Route53Change", Effect = "Allow", Action = ["route53:GetChange"], Resource = ["arn:${local.p}:route53:::change/*"] },
      { Sid = "SiteObjects", Effect = "Allow", Action = local.act.edge_site_object_write, Resource = [local.res[e].site_objects] },
      { Sid = "EdgeAlarms", Effect = "Allow", Action = concat(local.act.edge_alarm_write, local.act.edge_alarm_read), Resource = [local.res[e].alarm_us_east_1] },
      { Sid = "EdgeTopic", Effect = "Allow", Action = concat(local.act.edge_topic_write, local.act.edge_topic_read), Resource = [local.res[e].topic_us_east_1] },
    ]
  }) }
}
