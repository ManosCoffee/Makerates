# Data Engineer - Home assignment
We’re looking to understand your thought process, architectural approach, and use of best
practices. This does not need to be a production-ready solution, we want something you’d feel
comfortable presenting and discussing with our team.

## Assignment:
Our company plans to expand its payment options to support multiple currencies in addition to
the USD we currently offer. To achieve this, our analytics team needs to source external
currency rates. This source will enable us to convert currencies, verify the production source,
and provide a backup if necessary.
Your task is to:
- Evaluate market options:
    ○ Identify potential 2-3 sources for currency rates.
    ○ What attributes will you consider when selecting a source? Why?
    ○ Do you see any risks?
    ○ Describe your thought process in evaluating these options.
    Note: This does not need to be extremely detailed; focus on the key points mentioned above.
- Develop an extraction, transformation, and load module/s:
## ○ Extraction:
    ■ Extract currency rate data from the chosen source.
## ○ Transformation:
    ■ Convert the data into a format that facilitates easy currency conversion.
## ○ Load:
    ■ The storage aspect can be theoretical; you don't need to set up a
separate database or storage system. Just describe the storage method
you would choose.
    ○ Decide whether you will use an ETL or ELT approach and explain your choice.
- Module readiness:
    ○ Your module can range from a Proof of Concept (POC) to a production-ready
    implementation.
    ○ Use any tool or programming language you find suitable.
    ○ Describe why you chose this solution and approach.
    ○ Implement best practices as you see fit.
- Deployment and integration:
    ○ How would you approach deploying this module?
    ○ How do you envision this solution fitting into a broader data model?
    ○ Consider how you would communicate this project to the team and the company.
    ○ Explain the potential value of the final data to the organization.