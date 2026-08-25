from langchain_core.prompts import PromptTemplate

customer_support_template = PromptTemplate(
    input_variables=["customer_name", "product_name", "issue_description", "previous_interactions", "tone"],
    template="""
    You are a customer support specialist for {product_name}.
    
    Customer: {customer_name}
    Issue: {issue_description}
    Previous interactions: {previous_interactions}
    
    Respond to the customer in a {tone} tone. If you don't have enough information to resolve their issue,
    ask clarifying questions. Always prioritize customer satisfaction and accurate information.
    """
)

# This can now handle all types of customer inquiries with appropriate context
response = customer_support_chain.invoke({
    "customer_name": "Alex Smith",
    "product_name": "SmartHome Hub",
    "issue_description": "Device won't connect to WiFi after power outage",
    "previous_interactions": "Customer has already tried resetting the device twice.",
    "tone": "empathetic but technical"
})